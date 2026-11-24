"""Comparing two suite runs (Task 58)."""
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.workflow import NodeType, Workflow
from app.services.run_comparison import compare_runs, diff_workflows
from tests.conftest import DEMO_USER
from tests.test_suites import E, N, as_user, client, fake, make_suite, run_body  # noqa: F401  (fixtures and helpers)

BASE = "http://test"


def wf_dict(nodes=None, edges=None):
    nodes = nodes if nodes is not None else [N("s", NodeType.START), N("a", NodeType.TRANSFORM, "A"), N("e", NodeType.END)]
    edges = edges if edges is not None else [E("s", "a"), E("a", "e")]
    return Workflow(id="wf-1", name="W", nodes=nodes, edges=edges).model_dump(mode="json")


def case(cid, name=None, input=None, assertions=None, seed=None):
    return {"id": cid, "name": name or cid, "input": input or {}, "assertions": assertions or [], "tags": [], "seed": seed}


def run_row(rid, cases, workflow=None, mode="mock", seed=0, status="complete", suite="s1", created="2026-11-24T10:00:00+00:00"):
    return {"id": rid, "suite_id": suite, "status": status, "case_count": len(cases), "seed": seed, "llm_mode": mode,
            "workflow": workflow or wf_dict(), "cases": cases, "created_at": created}


def res(cid, status="passed", path=("s", "a", "e"), output=None, assertions=(), error=None, duration=5, llm=0, name=None):
    edges = [f"{a}→{b}" for a, b in zip(path, path[1:])]
    return {"case_id": cid, "status": status, "result": {
        "case_id": cid, "case_name": name or cid, "status": status, "duration_ms": duration, "llm_calls": llm, "error": error,
        "assertion_results": [dict(a, index=i) for i, a in enumerate(assertions)], "output": output,
        "path": list(path), "edges_taken": edges, "warnings": []}}


def check(label, passed, message="m", type_="equals"):
    return {"label": label, "type": type_, "passed": passed, "message": message}


def by_case(comparison):
    return {c.case_id: c for c in comparison.cases}


# ── Classification ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("before,after,expected", [
    ("passed", "passed", "unchanged"),
    ("passed", "failed", "regressed"),
    ("passed", "error", "regressed"),
    ("failed", "passed", "fixed"),
    ("error", "passed", "fixed"),
    ("failed", "failed", "still_failing"),
    ("failed", "error", "still_failing"),
    ("error", "failed", "still_failing"),
])
def test_status_transitions(before, after, expected):
    c = compare_runs(run_row("b", [case("c1")]), run_row("h", [case("c1")]), [res("c1", before)], [res("c1", after)])
    assert by_case(c)["c1"].change == expected
    assert (by_case(c)["c1"].base_status, by_case(c)["c1"].head_status) == (before, after)


def test_added_removed_and_incomplete_cases():
    base = run_row("b", [case("kept"), case("gone"), case("unfinished")])
    head = run_row("h", [case("kept"), case("new"), case("unfinished")])
    c = by_case(compare_runs(base, head, [res("kept"), res("gone"), res("unfinished")], [res("kept"), res("new")]))
    assert {k: v.change for k, v in c.items()} == {"kept": "unchanged", "gone": "removed", "new": "added", "unfinished": "incomplete"}
    assert c["gone"].head_status is None and c["new"].base_status is None and c["unfinished"].head_status is None


def test_cases_are_ordered_worst_first_and_summarised():
    cases = [case(f"c{i}") for i in range(6)]
    base = [res("c0"), res("c1"), res("c2", "failed"), res("c3", "failed"), res("c4"), res("c5")]
    head = [res("c0"), res("c1", "failed"), res("c2"), res("c3", "failed"), res("c4", "error"), res("c5")]
    c = compare_runs(run_row("b", cases), run_row("h", cases), base, head)
    assert [x.change for x in c.cases] == ["regressed", "regressed", "fixed", "still_failing", "unchanged", "unchanged"]
    s = c.summary
    assert (s.regressed, s.fixed, s.still_failing, s.unchanged, s.added, s.removed, s.incomplete) == (2, 1, 1, 2, 0, 0, 0)
    assert c.verdict == "regression"
    assert c.base.pass_rate == pytest.approx(4 / 6, abs=1e-3) and c.head.pass_rate == pytest.approx(3 / 6, abs=1e-3)
    assert s.pass_rate_delta == pytest.approx(-0.1667, abs=1e-3)


def test_verdicts():
    one = [case("c")]
    assert compare_runs(run_row("b", one), run_row("h", one), [res("c", "failed")], [res("c")]).verdict == "improvement"
    assert compare_runs(run_row("b", one), run_row("h", one), [res("c")], [res("c")]).verdict == "no_change"
    both = [case("a"), case("b")]
    assert compare_runs(run_row("b", both), run_row("h", both), [res("a"), res("b", "failed")], [res("a", "failed"), res("b")]).verdict == "regression"   # a regression always wins


def test_no_results_at_all():
    c = compare_runs(run_row("b", [case("c")]), run_row("h", [case("c")]), [], [])
    assert c.verdict == "no_change" and c.summary.pass_rate_delta is None and c.cases[0].change == "incomplete"


# ── What changed inside a case ───────────────────────────────────────────────

def test_path_output_and_cost_changes():
    cases = [case("c")]
    base = res("c", path=("s", "a", "e"), output={"v": 1}, duration=10, llm=1)
    head = res("c", path=("s", "b", "a", "e"), output={"v": 2}, duration=25, llm=3)
    d = by_case(compare_runs(run_row("b", cases), run_row("h", cases), [base], [head]))["c"]
    assert d.path_changed and d.nodes_added == ["b"] and d.nodes_removed == []
    assert d.output_changed and d.duration_delta_ms == 15 and d.llm_calls_delta == 2
    same = by_case(compare_runs(run_row("b", cases), run_row("h", cases), [base], [base]))["c"]
    assert not same.path_changed and not same.output_changed and same.duration_delta_ms == 0


def test_flipped_checks_are_listed_with_their_messages():
    cases = [case("c")]
    base = res("c", assertions=[check("tier", True, "ok"), check("total", True, "ok"), check("stays", False, "bad")])
    head = res("c", "failed", assertions=[check("tier", True, "ok"), check("total", False, "total is 3, expected 5"), check("stays", False, "bad")])
    d = by_case(compare_runs(run_row("b", cases), run_row("h", cases), [base], [head]))["c"]
    assert [(a.label, a.base_passed, a.head_passed) for a in d.assertion_changes] == [("total", True, False)]
    assert d.assertion_changes[0].head_message == "total is 3, expected 5"


def test_when_a_case_was_edited_checks_are_matched_by_label_not_position():
    old = case("c", assertions=[{"type": "equals", "path": "a", "value": 1}], input={"x": 1})
    new = case("c", assertions=[{"type": "equals", "path": "b", "value": 2}, {"type": "equals", "path": "a", "value": 1}], input={"x": 1})
    base = res("c", assertions=[check("a is 1", True)])
    head = res("c", "failed", assertions=[check("b is 2", False, "missing"), check("a is 1", True)])
    c = compare_runs(run_row("b", [old]), run_row("h", [new]), [base], [head])
    d = by_case(c)["c"]
    assert d.definition_changed
    assert [(a.label, a.base_passed, a.head_passed) for a in d.assertion_changes] == [("b is 2", None, False)]    # new check; "a is 1" matched, unchanged
    assert any("1 test case was edited" in w for w in c.warnings)


@pytest.mark.parametrize("edit", [{"input": {"x": 2}}, {"seed": 7}, {"assertions": [{"type": "exists", "path": "q"}]}])
def test_any_edit_to_input_seed_or_checks_counts_as_a_changed_definition(edit):
    a, b = case("c", input={"x": 1}), case("c", input={"x": 1}, **{k: v for k, v in edit.items() if k != "input"})
    if "input" in edit:
        b["input"] = edit["input"]
    assert by_case(compare_runs(run_row("b", [a]), run_row("h", [b]), [res("c")], [res("c")]))["c"].definition_changed


def test_renaming_a_case_is_not_a_definition_change():
    c = compare_runs(run_row("b", [case("c", name="Old")]), run_row("h", [case("c", name="New")]), [res("c")], [res("c")])
    assert by_case(c)["c"].case_name == "New" and not by_case(c)["c"].definition_changed


# ── Workflow diff ────────────────────────────────────────────────────────────

def test_workflow_diff_lists_steps_and_edges():
    before = wf_dict([N("s", NodeType.START), N("a", NodeType.LLM, "Draft", config={"prompt": "old", "model": "x"}), N("gone", NodeType.TOOL, "Old tool"), N("e", NodeType.END)],
                     [E("s", "a"), E("a", "gone"), E("gone", "e")])
    after = wf_dict([N("s", NodeType.START), N("a", NodeType.LLM, "Draft v2", config={"prompt": "new", "temperature": 0.2}), N("fresh", NodeType.API, "New API"), N("e", NodeType.END)],
                    [E("s", "a"), E("a", "fresh", "ok"), E("fresh", "e")])
    d = diff_workflows(before, after)
    assert d.changed
    nodes = {n.node_id: n for n in d.nodes}
    assert nodes["fresh"].change == "added" and nodes["gone"].change == "removed" and nodes["gone"].name == "Old tool"
    fields = {f.field: (f.before, f.after) for f in nodes["a"].fields}
    assert fields == {"name": ("Draft", "Draft v2"), "config.prompt": ("old", "new"), "config.model": ("x", None), "config.temperature": (None, 0.2)}
    edges = {(e.change, e.source, e.target, e.label) for e in d.edges}
    assert edges == {("added", "a", "fresh", "ok"), ("added", "fresh", "e", None), ("removed", "a", "gone", None), ("removed", "gone", "e", None)}
    assert next(e for e in d.edges if e.target == "fresh").target_name == "New API"


def test_type_schema_changes_are_reported_and_positions_are_not():
    a = wf_dict([N("s", NodeType.START), N("x", NodeType.LLM, "X"), N("e", NodeType.END)], [E("s", "x"), E("x", "e")])
    b = json.loads(json.dumps(a))
    b["nodes"][1]["type"] = "TOOL"
    b["nodes"][1]["output_schema"] = {"type": "object"}
    b["nodes"][0]["position"] = {"x": 999, "y": 999}                      # moving a node is not a change
    d = diff_workflows(a, b)
    assert [n.node_id for n in d.nodes] == ["x"]
    assert {f.field for f in d.nodes[0].fields} == {"type", "output_schema"}


def test_identical_workflows_have_no_diff_and_long_values_are_cut():
    assert not diff_workflows(wf_dict(), wf_dict()).changed
    a = wf_dict([N("s", NodeType.START), N("l", NodeType.LLM, config={"prompt": "x" * 2000}), N("e", NodeType.END)], [E("s", "l"), E("l", "e")])
    b = json.loads(json.dumps(a))
    b["nodes"][1]["config"]["prompt"] = "y" * 2000
    change = diff_workflows(a, b).nodes[0].fields[0]
    assert len(change.before) <= 300 and change.before.endswith("…") and change.before != change.after


# ── Coverage and warnings ────────────────────────────────────────────────────

def test_coverage_movement():
    wf = wf_dict([N("s", NodeType.START), N("a", NodeType.TRANSFORM, "A"), N("b", NodeType.TRANSFORM, "B"), N("e", NodeType.END)],
                 [E("s", "a"), E("s", "b"), E("a", "e"), E("b", "e")])
    cases = [case("c")]
    c = compare_runs(run_row("b", cases, wf), run_row("h", cases, wf),
                     [res("c", path=("s", "a", "e"))], [res("c", path=("s", "b", "e"))])
    assert c.coverage.nodes_newly_visited == ["b"] and c.coverage.nodes_no_longer_visited == ["a"]
    assert c.coverage.edges_newly_taken == ["b→e", "s→b"] and c.coverage.edges_no_longer_taken == ["a→e", "s→a"]


def warnings_of(base, head, base_results=None, head_results=None):
    cases = [case("c")]
    b = run_row("b", cases, **base)
    h = run_row("h", cases, **head)
    return compare_runs(b, h, base_results or [res("c")], head_results or [res("c")]).warnings


def test_warnings_for_runs_that_are_not_directly_comparable():
    assert any("one run used the real" in w.lower() for w in warnings_of({"mode": "mock"}, {"mode": "real"}))
    assert any("Both runs used the real AI model" in w for w in warnings_of({"mode": "real"}, {"mode": "real"}))
    assert any("different seeds (0 and 5)" in w for w in warnings_of({"seed": 0}, {"seed": 5}))
    assert warnings_of({}, {}) == []
    assert any("did not finish" in w for w in warnings_of({}, {"status": "cancelled"}))


def test_added_and_removed_cases_are_warned_about():
    c = compare_runs(run_row("b", [case("a"), case("old")]), run_row("h", [case("a"), case("new")]), [res("a"), res("old")], [res("a"), res("new")])
    assert any("1 case(s) added and 1 removed" in w for w in c.warnings)


def test_unexplained_regressions_are_flagged():
    cases = [case("c")]
    c = compare_runs(run_row("b", cases), run_row("h", cases), [res("c")], [res("c", "failed")])
    assert any("Nothing in the workflow or the test cases changed" in w for w in c.warnings)
    changed = wf_dict([N("s", NodeType.START), N("a", NodeType.TRANSFORM, "A", config={"x": 1}), N("e", NodeType.END)])
    c2 = compare_runs(run_row("b", cases), run_row("h", cases, changed), [res("c")], [res("c", "failed")])
    assert not any("Nothing in the workflow" in w for w in c2.warnings)               # a change explains it


def test_run_summaries():
    cases = [case("a"), case("b")]
    c = compare_runs(run_row("b", cases, mode="real"), run_row("h", cases, mode="real", seed=3),
                     [res("a", llm=2, duration=10), res("b", "failed", llm=3, duration=30)], [res("a", llm=1, duration=5), res("b", llm=1, duration=5)])
    assert (c.base.passed, c.base.failed, c.base.llm_calls, c.base.total_duration_ms, c.base.llm_mode) == (1, 1, 5, 40, "real")
    assert (c.head.passed, c.head.pass_rate, c.head.llm_calls, c.head.seed) == (2, 1.0, 2, 3)


# ── End to end through the API ───────────────────────────────────────────────

def routed(expression: str) -> Workflow:
    """START → CONDITION (expression over input.mode) → fast | slow → END"""
    return Workflow(
        id="wf-1", name="Router",
        nodes=[N("s", NodeType.START), N("c", NodeType.CONDITION, "Route", config={"expression": expression}),
               N("fast", NodeType.TRANSFORM, "Fast"), N("slow", NodeType.TRANSFORM, "Slow"), N("e", NodeType.END)],
        edges=[E("s", "c"), E("c", "fast", "fast"), E("c", "slow", "slow"), E("fast", "e"), E("slow", "e")],
    )


async def finish_run(c, suite_id, workflow):
    run = (await c.post(f"/api/suites/{suite_id}/runs", json=run_body(workflow))).json()
    for ref in run["cases"]:
        assert (await c.post(f"/api/suite-runs/{run['id']}/cases/{ref['id']}/run")).status_code == 200
    return run["id"]


@pytest.mark.asyncio
async def test_editing_a_workflow_shows_up_as_a_regression_with_its_cause(client, fake):
    async with client as c:
        body = {"name": "Routing", "workflow_id": "wf-1", "cases": [
            {"name": "fast case", "input": {"mode": "fast"}, "assertions": [{"type": "visits_node", "node_id": "fast"}]},
            {"name": "slow case", "input": {"mode": "slow"}, "assertions": [{"type": "visits_node", "node_id": "slow"}]},
        ]}
        suite_id = (await c.post("/api/suites", json=body)).json()["id"]

        base_id = await finish_run(c, suite_id, routed("input.mode"))                 # routes by the input: both pass
        head_id = await finish_run(c, suite_id, routed("'fast'"))                      # a "refactor" that always takes the fast branch

        res = await c.get(f"/api/suite-runs/compare?base={base_id}&head={head_id}")
        assert res.status_code == 200, res.text
        cmp = res.json()

    assert cmp["verdict"] == "regression"
    assert (cmp["base"]["passed"], cmp["head"]["passed"]) == (2, 1) and cmp["summary"]["pass_rate_delta"] == -0.5
    first = cmp["cases"][0]
    assert first["case_name"] == "slow case" and first["change"] == "regressed"
    assert first["nodes_added"] == ["fast"] and first["nodes_removed"] == ["slow"]
    assert first["assertion_changes"][0]["base_passed"] is True and first["assertion_changes"][0]["head_passed"] is False
    assert "slow" in first["assertion_changes"][0]["head_message"]
    # …and the workflow diff points at what changed:
    [node] = cmp["workflow"]["nodes"]
    assert node["node_id"] == "c" and node["fields"] == [{"field": "config.expression", "before": "input.mode", "after": "'fast'"}]
    assert cmp["coverage"]["nodes_no_longer_visited"] == ["slow"]
    assert cmp["warnings"] == []                                                       # the change explains it: no "unexplained" warning


@pytest.mark.asyncio
async def test_reversing_the_comparison_turns_a_regression_into_an_improvement(client, fake):
    async with client as c:
        body = {"name": "S", "workflow_id": "wf-1", "cases": [{"name": "slow case", "input": {"mode": "slow"}, "assertions": [{"type": "visits_node", "node_id": "slow"}]}]}
        suite_id = (await c.post("/api/suites", json=body)).json()["id"]
        good = await finish_run(c, suite_id, routed("input.mode"))
        bad = await finish_run(c, suite_id, routed("'fast'"))
        forward = (await c.get(f"/api/suite-runs/compare?base={good}&head={bad}")).json()
        backward = (await c.get(f"/api/suite-runs/compare?base={bad}&head={good}")).json()
    assert forward["verdict"] == "regression" and backward["verdict"] == "improvement"
    assert backward["cases"][0]["change"] == "fixed"


@pytest.mark.asyncio
async def test_comparison_input_checks(client, fake, as_user):
    async with client as c:
        suite_a = await make_suite(c, n=1)
        suite_b = (await make_suite(c, n=1, name="other"))
        a1 = await finish_run(c, suite_a["id"], routed("input.mode"))
        a2 = await finish_run(c, suite_a["id"], routed("input.mode"))
        b1 = await finish_run(c, suite_b["id"], routed("input.mode"))

        assert (await c.get(f"/api/suite-runs/compare?base={a1}&head={a1}")).status_code == 422
        diff_suites = await c.get(f"/api/suite-runs/compare?base={a1}&head={b1}")
        assert diff_suites.status_code == 422 and "different suites" in diff_suites.json()["detail"]
        assert (await c.get(f"/api/suite-runs/compare?base=not-a-uuid&head={a2}")).status_code == 404
        assert (await c.get(f"/api/suite-runs/compare?base={uuid.uuid4()}&head={a2}")).status_code == 404
        assert (await c.get(f"/api/suite-runs/compare?base={a1}")).status_code == 422          # a missing parameter is not mistaken for a run id
        assert (await c.get(f"/api/suite-runs/compare?base={a1}&head={a2}")).status_code == 200

        as_user(DEMO_USER)                                                                      # someone else's runs are invisible
        assert (await c.get(f"/api/suite-runs/compare?base={a1}&head={a2}")).status_code == 404


@pytest.mark.asyncio
async def test_comparison_requires_auth(fake):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as c:
        assert (await c.get(f"/api/suite-runs/compare?base={uuid.uuid4()}&head={uuid.uuid4()}")).status_code in (401, 403)
