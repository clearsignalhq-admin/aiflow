"""Suggested changes: applying them, deterministic fixes, AI proposals (Task 59)."""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.main import app
from app.models.workflow import NodeType, Workflow
from app.schemas.patch import (
    AddEdge, AddNode, ApplyRequest, Change, RemoveEdge, RemoveNode, UpdateEdge, UpdateNode,
)
from app.schemas.simulation import SimulationSettings
from app.services.change_suggester import SuggestionError, parse_suggestions, suggest_changes
from app.services.fixes import suggest_fixes
from app.services.linter import lint_workflow
from app.services.patching import apply_changes, check_applies, describe, view
from app.services.simulator import simulate
from tests.test_run_comparison import E, N  # noqa: F401
from tests.test_suites import APPROVED_USER, as_user  # noqa: F401

BASE = "http://test"


def wf(nodes, edges):
    return Workflow(id="w", name="W", nodes=nodes, edges=edges)


def simple():
    return wf([N("s", NodeType.START), N("a", NodeType.TRANSFORM, "A"), N("e", NodeType.END)], [E("s", "a"), E("a", "e")])


def change(*ops, cid="c1"):
    return Change(id=cid, title="t", ops=list(ops))


def rules(workflow):
    return {(f.rule_id, f.node_id) for f in lint_workflow(workflow).findings}


# ── Operations ───────────────────────────────────────────────────────────────

def test_add_node_and_edges_places_new_step_and_connects():
    out = apply_changes(simple(), [change(
        AddNode(op="add_node", id="llm", type=NodeType.LLM, name="Summarise", config={"prompt": "p"}, near="a"),
        RemoveEdge(op="remove_edge", source="a", target="e"),
        AddEdge(op="add_edge", source="a", target="llm"), AddEdge(op="add_edge", source="llm", target="e"),
    )])
    assert out.applied == ["c1"] and out.added_node_ids == ["llm"]
    w = out.workflow
    node = next(n for n in w.nodes if n.id == "llm")
    a = next(n for n in w.nodes if n.id == "a")
    assert node.config == {"prompt": "p"} and node.position.x > a.position.x
    assert {(e.source, e.target) for e in w.edges} == {("s", "a"), ("a", "llm"), ("llm", "e")}


def test_new_steps_do_not_land_on_existing_ones():
    out = apply_changes(simple(), [change(*[AddNode(op="add_node", id=f"n{i}", type=NodeType.TRANSFORM, name=f"N{i}", near="a") for i in range(4)])])
    spots = [(n.position.x, n.position.y) for n in out.workflow.nodes if n.id.startswith("n")]
    assert len(spots) == 4 and len(set(spots)) == 4


def test_update_node_changes_only_what_is_given():
    base = wf([N("s", NodeType.START), N("l", NodeType.LLM, "L", config={"prompt": "old", "model": "m"}, output_schema={"type": "object"}), N("e", NodeType.END)], [E("s", "l"), E("l", "e")])
    out = apply_changes(base, [change(UpdateNode(op="update_node", id="l", config_set={"prompt": "new"}, config_unset=["model"]))]).workflow
    node = next(n for n in out.nodes if n.id == "l")
    assert node.config == {"prompt": "new"} and node.name == "L" and node.output_schema == {"type": "object"}
    cleared = apply_changes(base, [change(UpdateNode(op="update_node", id="l", output_schema=None))]).workflow
    assert next(n for n in cleared.nodes if n.id == "l").output_schema is None            # explicit null clears
    renamed = apply_changes(base, [change(UpdateNode(op="update_node", id="l", name="Z"))]).workflow
    assert next(n for n in renamed.nodes if n.id == "l").output_schema == {"type": "object"}   # absent means untouched


def test_remove_node_removes_its_edges_and_update_edge_relabels():
    base = wf([N("s", NodeType.START), N("c", NodeType.CONDITION), N("x", NodeType.TRANSFORM), N("e", NodeType.END)],
              [E("s", "c"), E("c", "x", "a"), E("c", "e", "b"), E("x", "e")])
    out = apply_changes(base, [change(RemoveNode(op="remove_node", id="x"), UpdateEdge(op="update_edge", source="c", target="e", condition="b", set_condition="c"))]).workflow
    assert {(e.source, e.target, e.condition) for e in out.edges} == {("s", "c", None), ("c", "e", "c")}


@pytest.mark.parametrize("op,reason", [
    (RemoveNode(op="remove_node", id="s"), "START"),
    (RemoveNode(op="remove_node", id="e"), "END"),
    (RemoveNode(op="remove_node", id="nope"), "no step"),
    (AddNode(op="add_node", id="a", type=NodeType.LLM, name="dup"), "already exists"),
    (AddNode(op="add_node", id="s2", type=NodeType.START, name="x"), "START"),
    (AddEdge(op="add_edge", source="e", target="a"), "END"),
    (AddEdge(op="add_edge", source="a", target="s"), "START"),
    (AddEdge(op="add_edge", source="a", target="a"), "itself"),
    (AddEdge(op="add_edge", source="a", target="ghost"), "no step"),
    (RemoveEdge(op="remove_edge", source="s", target="e"), "no connection"),
    (UpdateEdge(op="update_edge", source="s", target="a", condition="zzz", set_condition="y"), "labelled"),
    (UpdateNode(op="update_node", id="ghost", name="x"), "no step"),
])
def test_bad_operations_are_skipped_with_a_reason(op, reason):
    out = apply_changes(simple(), [change(op)])
    assert out.applied == [] and reason in out.skipped[0].reason
    assert out.workflow == simple()                                                  # nothing partially applied


def test_a_change_is_all_or_nothing_and_others_still_apply():
    good = change(UpdateNode(op="update_node", id="a", name="Renamed"), cid="good")
    bad = change(UpdateNode(op="update_node", id="a", name="Half"), RemoveNode(op="remove_node", id="ghost"), cid="bad")
    out = apply_changes(simple(), [bad, good, good.model_copy()])
    assert out.applied == ["good"] and [s.id for s in out.skipped] == ["bad", "good"]
    assert next(n for n in out.workflow.nodes if n.id == "a").name == "Renamed"
    assert "more than once" in out.skipped[1].reason


def test_later_changes_see_earlier_ones():
    first = change(AddNode(op="add_node", id="n", type=NodeType.TRANSFORM, name="N"), cid="one")
    second = change(AddEdge(op="add_edge", source="a", target="n"), cid="two")
    assert apply_changes(simple(), [first, second]).applied == ["one", "two"]
    assert apply_changes(simple(), [second, first]).applied == ["one"]


def test_applying_never_mutates_the_input():
    before = simple().model_dump()
    w = simple()
    apply_changes(w, [change(RemoveNode(op="remove_node", id="a"))])
    assert w.model_dump() == before


def test_step_limits_are_enforced():
    from app.models.workflow import MAX_NODES
    nodes = [N("s", NodeType.START), N("e", NodeType.END)] + [N(f"n{i}", NodeType.TRANSFORM) for i in range(MAX_NODES - 2)]
    full = wf(nodes, [])
    out = apply_changes(full, [change(AddNode(op="add_node", id="extra", type=NodeType.TRANSFORM, name="x"))])
    assert "exceed" in out.skipped[0].reason


def test_a_suggestion_with_display_fields_can_be_posted_back():
    posted = view(simple(), change(AddNode(op="add_node", id="n", type=NodeType.TRANSFORM, name="N"))).model_dump(mode="json")
    assert posted["summary"] and Change.model_validate(posted).ops[0].id == "n"


def test_unknown_or_malformed_operations_are_rejected_by_the_schema():
    with pytest.raises(ValidationError):
        Change.model_validate({"id": "x", "title": "t", "ops": [{"op": "drop_database"}]})
    with pytest.raises(ValidationError):
        Change.model_validate({"id": "x", "title": "t", "ops": [{"op": "remove_node", "id": "a", "extra": 1}]})
    with pytest.raises(ValidationError):
        Change.model_validate({"id": "x", "title": "t", "ops": [{"op": "add_node", "id": "bad id!", "type": "LLM", "name": "n"}]})
    with pytest.raises(ValidationError):
        Change.model_validate({"id": "x", "title": "t", "ops": []})


def test_descriptions_use_step_names():
    c = change(AddNode(op="add_node", id="n", type=NodeType.HITL, name="Approve"), AddEdge(op="add_edge", source="a", target="n", condition="ok"),
               UpdateNode(op="update_node", id="a", config_set={"x": 1}), RemoveNode(op="remove_node", id="e"))
    assert describe(simple(), c) == ["Add HITL step “Approve”", "Connect “A” → “Approve” (label: ok)", "Change “A”: set x", "Remove step “E” and its connections".replace("E", "e")]
    v = view(simple(), c)
    assert v.touches == ["n", "a", "e"] and v.summary[0].startswith("Add HITL")


# ── Deterministic fixes ──────────────────────────────────────────────────────

def fix_all(workflow):
    fixes = suggest_fixes(workflow)
    return fixes, apply_changes(workflow, fixes)


def test_clean_workflow_has_no_fixes():
    assert suggest_fixes(simple()) == []


def test_unreachable_and_dead_end_fixes():
    w = wf([N("s", NodeType.START), N("a", NodeType.TRANSFORM, "A"), N("dead", NodeType.TRANSFORM, "Dead"), N("orphan", NodeType.TRANSFORM, "Orphan"), N("e", NodeType.END)],
           [E("s", "a"), E("s", "dead")])
    fixes, out = fix_all(w)
    by_id = {c.id: c for c in fixes}
    assert "unreachable-node:orphan" in by_id and "dead-end:a" in by_id and "dead-end:dead" in by_id
    assert out.skipped == [] or all(s.id.startswith("unreachable") for s in out.skipped)
    assert rules(out.workflow) == set()


def test_condition_fixes_label_and_add_second_branch():
    w = wf([N("s", NodeType.START), N("c", NodeType.CONDITION, "C", config={"expression": "true"}), N("x", NodeType.TRANSFORM), N("y", NodeType.TRANSFORM), N("e", NodeType.END)],
           [E("s", "c"), E("c", "x"), E("c", "y"), E("x", "e"), E("y", "e")])
    fixes, out = fix_all(w)
    assert [c.id for c in fixes] == ["condition-unlabelled-branch:c"]
    assert sorted(e.condition for e in out.workflow.edges if e.source == "c") == ["false", "true"]
    one = wf([N("s", NodeType.START), N("c", NodeType.CONDITION, "C"), N("x", NodeType.TRANSFORM), N("e", NodeType.END)], [E("s", "c"), E("c", "x", "true"), E("x", "e")])
    fixes, out = fix_all(one)
    assert [(e.target, e.condition) for e in out.workflow.edges if e.source == "c"] == [("x", "true"), ("e", "false")]
    assert not any(r for r, n in rules(out.workflow) if r.startswith("condition-"))


def test_missing_schema_fields_are_declared_upstream():
    w = wf([N("s", NodeType.START), N("l", NodeType.LLM, "L"), N("c", NodeType.CONDITION, "C", config={"expression": "output.score > 3"}), N("x", NodeType.TRANSFORM), N("e", NodeType.END)],
           [E("s", "l"), E("l", "c"), E("c", "x", "true"), E("c", "e", "false"), E("x", "e")])
    assert ("condition-input-undeclared", "l") in rules(w)
    _, out = fix_all(w)
    assert next(n for n in out.workflow.nodes if n.id == "l").output_schema == {"type": "object", "properties": {"score": {}}}
    assert ("condition-input-undeclared", "l") not in rules(out.workflow)

    declared = wf([N("s", NodeType.START), N("l", NodeType.LLM, "L", output_schema={"type": "object", "properties": {"other": {"type": "string"}}}),
                   N("c", NodeType.CONDITION, "C", config={"expression": "output.score > 3"}), N("e", NodeType.END)],
                  [E("s", "l"), E("l", "c"), E("c", "e", "true"), E("c", "e", "false")])
    assert ("condition-input-missing-field", "c") in rules(declared)
    _, out = fix_all(declared)
    props = next(n for n in out.workflow.nodes if n.id == "l").output_schema["properties"]
    assert set(props) == {"other", "score"} and props["other"] == {"type": "string"}      # existing property kept
    assert ("condition-input-missing-field", "c") not in rules(out.workflow)


@pytest.mark.asyncio
async def test_failure_branch_fix_resolves_the_finding_and_still_simulates():
    w = wf([N("s", NodeType.START), N("api", NodeType.API, "Fetch", config={"url": "https://example.com", "method": "GET"}), N("e", NodeType.END)],
           [E("s", "api"), E("api", "e")])
    assert ("no-failure-branch", "api") in rules(w)
    fixes, out = fix_all(w)
    assert [c.id for c in fixes] == ["no-failure-branch:api"] and out.skipped == []
    fixed = out.workflow
    assert ("no-failure-branch", "api") not in rules(fixed)
    assert sorted(n.type.value for n in fixed.nodes) == ["API", "CONDITION", "END", "HITL", "START"]
    trace = await simulate(fixed, {}, SimulationSettings())
    assert trace.status == "complete"                                                  # the new condition reads a field the API now declares
    assert "api" in [x.node_id for x in trace.steps]
    assert next(n for n in fixed.nodes if n.id == "api").output_schema["properties"]["ok"] == {"type": "boolean", "enum": [True]}
    check = next(s for s in trace.steps if s.node_type == "CONDITION")
    assert check.warnings == [] and len(check.next_ids) == 1                           # it decides: success path only, not "follow every branch"
    assert not any(n.type.value == "HITL" and n.id in [s.node_id for s in trace.steps] for n in fixed.nodes)   # the failure review is not visited


def test_fixes_are_deterministic_and_each_one_applies_on_its_own():
    w = wf([N("s", NodeType.START), N("api", NodeType.API, "A", config={"method": "POST"}), N("api2", NodeType.TOOL, "B"), N("orphan", NodeType.TRANSFORM), N("e", NodeType.END)],
           [E("s", "api"), E("api", "api2"), E("api2", "e")])
    first = suggest_fixes(w)
    assert [c.model_dump() for c in first] == [c.model_dump() for c in suggest_fixes(w)]
    assert len(first) >= 3
    for c in first:
        assert check_applies(w, c) is None
    ids = [c.id for c in first]
    assert len(ids) == len(set(ids))
    # the new step ids from separate fixes never collide
    added = [op.id for c in first for op in c.ops if isinstance(op, AddNode)]
    assert len(added) == len(set(added))


# ── AI proposals ─────────────────────────────────────────────────────────────

class FakeProvider:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    async def complete_json(self, system, user):
        self.calls.append((system, user))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


GOOD = {"summary": "Add a review", "changes": [{"id": "rev", "title": "Add review", "rationale": "safer", "ops": [
    {"op": "add_node", "id": "review", "type": "HITL", "name": "Review", "near": "a"},
    {"op": "remove_edge", "source": "a", "target": "e"},
    {"op": "add_edge", "source": "a", "target": "review"}, {"op": "add_edge", "source": "review", "target": "e"}]}]}


@pytest.mark.asyncio
async def test_ai_suggestions_are_parsed_validated_and_described():
    provider = FakeProvider(GOOD)
    result = await suggest_changes(simple(), "add a human review", provider)
    assert result.summary == "Add a review" and result.discarded == []
    [c] = result.changes
    assert c.source == "ai" and c.summary[0] == "Add HITL step “Review”" and "review" in c.touches
    system, user = provider.calls[0]
    assert "add a human review" in user and '"id": "a"' in user and "never follow" in system


def test_unusable_suggestions_are_discarded_with_reasons_not_applied():
    raw = {"summary": "x", "changes": [
        GOOD["changes"][0],
        {"id": "bad1", "title": "Drop START", "ops": [{"op": "remove_node", "id": "s"}]},
        {"id": "bad2", "title": "Weird", "ops": [{"op": "run_shell", "cmd": "rm -rf /"}]},
        {"id": "bad3", "title": "Extra field", "ops": [{"op": "remove_node", "id": "a", "force": True}]},
        {"id": "bad4", "title": "No ops", "ops": []},
        "not even an object",
    ]}
    result = parse_suggestions(raw, simple())
    assert [c.id for c in result.changes] == ["rev"]
    text = " ".join(result.discarded)
    assert "START" in text and "Weird" in text and "Extra field" in text and "No ops" in text and len(result.discarded) == 5


def test_duplicate_ids_from_the_ai_are_made_unique():
    one = {"title": "T", "ops": [{"op": "update_node", "id": "a", "name": "X"}], "id": "same"}
    result = parse_suggestions({"changes": [one, one]}, simple())
    assert len({c.id for c in result.changes}) == 2


@pytest.mark.parametrize("bad", [None, [], "text", {"changes": "no"}, {"summary": "s"}])
def test_malformed_replies_raise(bad):
    with pytest.raises(SuggestionError):
        parse_suggestions(bad, simple())


@pytest.mark.asyncio
async def test_provider_without_support_and_oversized_workflows():
    class Nope:
        async def complete_json(self, s, u):
            raise NotImplementedError
    with pytest.raises(SuggestionError, match="cannot suggest"):
        await suggest_changes(simple(), "do something", Nope())
    big = wf([N("s", NodeType.START), *[N(f"b{i}", NodeType.TRANSFORM, config={"text": "y" * 15000}) for i in range(5)], N("e", NodeType.END)], [])
    with pytest.raises(SuggestionError, match="too large"):
        await suggest_changes(big, "do something", FakeProvider(GOOD))


# ── HTTP ─────────────────────────────────────────────────────────────────────

def http():
    return AsyncClient(transport=ASGITransport(app=app), base_url=BASE)


@pytest.fixture
def usage():
    with patch("app.api.routes.get_usage_today", AsyncMock(return_value={})), patch("app.api.routes.increment_usage", AsyncMock()) as inc:
        yield inc


@pytest.mark.asyncio
async def test_fixes_endpoint_costs_nothing(as_user, usage):
    as_user(APPROVED_USER)
    w = wf([N("s", NodeType.START), N("api", NodeType.API, "Fetch"), N("e", NodeType.END)], [E("s", "api"), E("api", "e")])
    async with http() as c:
        res = await c.post("/api/workflows/fixes", json={"workflow": w.model_dump(mode="json")})
    assert res.status_code == 200
    [fix] = res.json()["changes"]
    assert fix["id"] == "no-failure-branch:api" and fix["summary"] and fix["ops"][0]["op"] == "update_node"
    usage.assert_not_called()


@pytest.mark.asyncio
async def test_apply_endpoint_round_trips_a_fix(as_user, usage):
    as_user(APPROVED_USER)
    w = wf([N("s", NodeType.START), N("orphan", NodeType.TRANSFORM, "O"), N("a", NodeType.TRANSFORM), N("e", NodeType.END)], [E("s", "a"), E("a", "e")])
    async with http() as c:
        fixes = (await c.post("/api/workflows/fixes", json={"workflow": w.model_dump(mode="json")})).json()["changes"]
        res = await c.post("/api/workflows/apply-changes", json={"workflow": w.model_dump(mode="json"), "changes": fixes})
        bad = await c.post("/api/workflows/apply-changes", json={"workflow": w.model_dump(mode="json"), "changes": [{"id": "x", "title": "t", "ops": [{"op": "nuke"}]}]})
        empty = await c.post("/api/workflows/apply-changes", json={"workflow": w.model_dump(mode="json"), "changes": []})
    body = res.json()
    assert res.status_code == 200 and body["applied"] == ["unreachable-node:orphan"] and [n["id"] for n in body["workflow"]["nodes"]] == ["s", "a", "e"]
    assert bad.status_code == 422 and empty.status_code == 422


@pytest.mark.asyncio
async def test_suggest_endpoint_uses_the_allowance_and_reports_errors(as_user, usage):
    as_user(APPROVED_USER)
    payload = {"workflow": simple().model_dump(mode="json"), "instruction": "add a human review"}
    async with http() as c:
        with patch("app.api.routes.get_provider", return_value=FakeProvider(GOOD)):
            ok = await c.post("/api/workflows/suggest", json=payload)
        with patch("app.api.routes.get_provider", side_effect=RuntimeError("LLM_API_KEY is not set")):
            no_key = await c.post("/api/workflows/suggest", json=payload)
        with patch("app.api.routes.get_provider", return_value=FakeProvider({"oops": 1})):
            garbage = await c.post("/api/workflows/suggest", json=payload)
        with patch("app.api.routes.get_provider", return_value=FakeProvider(RuntimeError("upstream down"))):
            failed = await c.post("/api/workflows/suggest", json=payload)
        short = await c.post("/api/workflows/suggest", json={**payload, "instruction": "x"})
    assert ok.status_code == 200 and ok.json()["changes"][0]["id"] == "rev"
    assert no_key.status_code == 503 and garbage.status_code == 422 and failed.status_code == 502 and short.status_code == 422
    assert usage.await_count == 1                                                     # only the successful call is charged


@pytest.mark.asyncio
async def test_suggest_endpoint_respects_the_daily_limit(as_user):
    as_user(APPROVED_USER)
    payload = {"workflow": simple().model_dump(mode="json"), "instruction": "add a human review"}
    with patch("app.api.routes.get_usage_today", AsyncMock(return_value={"llm_requests": 10_000})), patch("app.api.routes.settings.approved_max_llm_requests_per_day", 5):
        async with http() as c:
            res = await c.post("/api/workflows/suggest", json=payload)
    assert res.status_code == 429


@pytest.mark.asyncio
async def test_endpoints_require_auth():
    async with http() as c:
        for path, body in [("fixes", {}), ("suggest", {}), ("apply-changes", {})]:
            assert (await c.post(f"/api/workflows/{path}", json=body)).status_code in (401, 403, 422)
