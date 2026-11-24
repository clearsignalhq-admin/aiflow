"""Failure injection, resilience drill and injection exposure (Task 60)."""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.workflow import NodeType, Workflow
from app.schemas.simulation import FailureKind, InjectedFailure, SimulationSettings
from app.services.fixes import suggest_fixes
from app.services.injection_exposure import analyse_exposure
from app.services.patching import apply_changes
from app.services.resilience import MAX_DRILL_STEPS, run_drill
from app.services.simulator import simulate
from tests.test_run_comparison import E, N  # noqa: F401
from tests.test_suites import APPROVED_USER, as_user  # noqa: F401

BASE = "http://test"


def wf(nodes, edges):
    return Workflow(id="w", name="W", nodes=nodes, edges=edges)


def api(id="api", **cfg):
    return N(id, NodeType.API, id.title(), config={"url": "https://x.test", "method": "GET", **cfg})


def unhandled():
    """START → API → TRANSFORM → END: nothing looks at the API result."""
    return wf([N("s", NodeType.START), api(), N("t", NodeType.TRANSFORM, "Tidy"), N("e", NodeType.END)], [E("s", "api"), E("api", "t"), E("t", "e")])


def handled():
    """START → API → CONDITION(output.ok) → TRANSFORM | HITL → END"""
    return wf(
        [N("s", NodeType.START), N("api", NodeType.API, "Api", config={"url": "https://x.test", "method": "GET", "mock_output": {"ok": True, "v": 1}}),
         N("c", NodeType.CONDITION, "Check", config={"expression": "output.ok"}), N("t", NodeType.TRANSFORM, "Use it"),
         N("h", NodeType.HITL, "Review failure"), N("e", NodeType.END)],
        [E("s", "api"), E("api", "c"), E("c", "t", "true"), E("c", "h", "false"), E("t", "e"), E("h", "e")])


# ── Injection in the simulator ───────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("kind,expected", [
    (FailureKind.ERROR, {"ok": False, "status": 500}),
    (FailureKind.EMPTY, {}),
    (FailureKind.MALFORMED, {"raw": "<html>"}),
])
async def test_injected_output_replaces_the_real_one(kind, expected):
    trace = await simulate(unhandled(), {}, SimulationSettings(inject=InjectedFailure(node_id="api", kind=kind)))
    step = next(s for s in trace.steps if s.node_id == "api")
    assert trace.status == "complete" and step.status.value == "success"
    for k, v in expected.items():
        assert str(v) in str(step.output.get(k, "")) or step.output.get(k) == v
    assert any("Injected failure" in w for w in step.warnings)
    others = [s for s in trace.steps if s.node_id != "api"]
    assert all(not s.warnings for s in others if s.node_id != "e")


@pytest.mark.asyncio
async def test_a_timeout_stops_the_run_at_that_step():
    trace = await simulate(unhandled(), {}, SimulationSettings(inject=InjectedFailure(node_id="api", kind=FailureKind.TIMEOUT)))
    assert trace.status == "error"
    assert trace.steps[-1].node_id == "api" and "timed out" in trace.steps[-1].error


@pytest.mark.asyncio
async def test_no_injection_changes_nothing_and_unknown_nodes_are_harmless():
    clean = await simulate(unhandled(), {}, SimulationSettings())
    ghost = await simulate(unhandled(), {}, SimulationSettings(inject=InjectedFailure(node_id="nope", kind=FailureKind.ERROR)))
    assert [s.output for s in clean.steps] == [s.output for s in ghost.steps]


# ── Resilience drill ─────────────────────────────────────────────────────────

def verdicts(report):
    return {(r.node_id, r.kind.value): r.verdict for r in report.results}


@pytest.mark.asyncio
async def test_unhandled_failures_are_ignored_or_halt():
    report = await run_drill(unhandled(), {})
    v = verdicts(report)
    assert v[("api", "timeout")] == "halted"
    assert v[("api", "error")] == "ignored" and v[("api", "empty")] == "ignored" and v[("api", "malformed")] == "ignored"
    assert report.summary.total == 4 and report.summary.ignored == 3 and report.summary.halted == 1 and report.summary.handled == 0
    assert report.results[0].verdict == "ignored"                                        # worst first
    assert "passed along without being noticed" in next(r for r in report.results if r.kind == FailureKind.ERROR).detail


@pytest.mark.asyncio
async def test_a_failure_branch_is_recognised_as_handling_the_error():
    report = await run_drill(handled(), {})
    v = verdicts(report)
    assert v[("api", "error")] == "handled"
    detail = next(r for r in report.results if r.kind == FailureKind.ERROR).detail
    assert "now goes through “Review failure”" in detail and "no longer reaches “Use it”" in detail
    assert v[("api", "timeout")] == "halted"                                              # an exception is not a payload
    assert v[("api", "empty")] == "halted"                                                # the check reads a field that is not there
    empty = next(r for r in report.results if r.kind == FailureKind.EMPTY)
    assert "could not make its decision" in empty.detail and "“Check”" in empty.detail
    assert report.baseline_path[0] == "s" and "t" in report.baseline_path


@pytest.mark.asyncio
async def test_the_suggested_failure_branch_fix_turns_ignored_into_handled():
    before = await run_drill(unhandled(), {})
    fixed = apply_changes(unhandled(), suggest_fixes(unhandled())).workflow
    after = await run_drill(fixed, {})
    assert verdicts(before)[("api", "error")] == "ignored"
    assert verdicts(after)[("api", "error")] == "handled"


@pytest.mark.asyncio
async def test_only_external_steps_that_ran_are_tested():
    w = wf([N("s", NodeType.START), N("c", NodeType.CONDITION, "Pick", config={"expression": "input.go"}), api("a"), api("b"), N("e", NodeType.END)],
           [E("s", "c"), E("c", "a", "true"), E("c", "b", "false"), E("a", "e"), E("b", "e")])
    report = await run_drill(w, {"go": True})
    assert {r.node_id for r in report.results} == {"a"} and report.not_reached == ["b"]
    assert any("did not run with this input" in n for n in report.notes)
    other = await run_drill(w, {"go": False})
    assert {r.node_id for r in other.results} == {"b"}


@pytest.mark.asyncio
async def test_a_workflow_that_already_fails_is_not_drilled():
    failing = unhandled()
    broken = await simulate(failing, {}, SimulationSettings(inject=InjectedFailure(node_id="api", kind=FailureKind.TIMEOUT)))
    with patch("app.services.resilience.simulate", AsyncMock(return_value=broken)):
        report = await run_drill(failing, {})
    assert report.baseline_status == "error" and report.results == [] and "Fix that first" in report.notes[0]


@pytest.mark.asyncio
async def test_large_workflows_are_capped():
    n = MAX_DRILL_STEPS + 5
    nodes = [N("s", NodeType.START)] + [api(f"a{i}") for i in range(n)] + [N("e", NodeType.END)]
    edges = [E("s", "a0")] + [E(f"a{i}", f"a{i + 1}") for i in range(n - 1)] + [E(f"a{n - 1}", "e")]
    report = await run_drill(wf(nodes, edges), {})
    assert report.skipped == 5 and report.summary.total == MAX_DRILL_STEPS * 4 and any("left out" in x for x in report.notes)


@pytest.mark.asyncio
async def test_llm_steps_can_be_drilled_and_start_end_cannot():
    w = wf([N("s", NodeType.START), N("l", NodeType.LLM, "Draft"), N("e", NodeType.END)], [E("s", "l"), E("l", "e")])
    report = await run_drill(w, {})
    assert {r.node_id for r in report.results} == {"l"}


# ── Injection exposure ───────────────────────────────────────────────────────

def rag_llm_refund(gated=False):
    mid = [N("h", NodeType.HITL, "Approve")] if gated else []
    edges = [E("s", "rag"), E("rag", "llm"), E("llm", "h" if gated else "pay"), E("pay", "e")]
    if gated:
        edges.insert(3, E("h", "pay"))
        edges.remove(E("llm", "h"))
        edges.insert(3, E("llm", "h"))
    return wf([N("s", NodeType.START), N("rag", NodeType.RAG, "Policies"), N("llm", NodeType.LLM, "Decide"), *mid,
               N("pay", NodeType.API, "Issue refund", config={"method": "POST", "url": "https://pay.test"}), N("e", NodeType.END)], edges)


def test_untrusted_text_reaching_a_write_is_high_exposure():
    report = analyse_exposure(rag_llm_refund())
    [x] = report.exposures
    assert x.severity == "high" and x.node_id == "llm"
    assert {s.kind for s in x.sources} == {"user input", "retrieved documents"}
    assert [(s.name, s.action, s.gated) for s in x.sinks] == [("Issue refund", "writes through an API", False)]
    assert "Issue refund" in x.message and "human review" in x.advice


def test_a_human_review_in_between_lowers_it_to_low():
    [x] = analyse_exposure(rag_llm_refund(gated=True)).exposures
    assert x.severity == "low" and x.sinks[0].gated and "stands in between" in x.message


def test_review_on_only_one_of_two_paths_still_counts_as_open():
    w = wf([N("s", NodeType.START), N("llm", NodeType.LLM, "L"), N("h", NodeType.HITL), N("c", NodeType.CONDITION, config={"expression": "input.x"}),
            N("pay", NodeType.DATABASE, "Update", config={"query": "UPDATE t SET a = 1"}), N("e", NodeType.END)],
           [E("s", "llm"), E("llm", "c"), E("c", "h", "true"), E("c", "pay", "false"), E("h", "pay"), E("pay", "e")])
    [x] = analyse_exposure(w).exposures
    assert x.severity == "high" and x.sinks[0].action == "writes to a database" and not x.sinks[0].gated


def test_a_tool_call_is_medium_and_reads_are_not_sinks():
    tool = wf([N("s", NodeType.START), N("llm", NodeType.LLM), N("t", NodeType.TOOL, "Send email"), N("e", NodeType.END)], [E("s", "llm"), E("llm", "t"), E("t", "e")])
    assert analyse_exposure(tool).exposures[0].severity == "medium"
    reads = wf([N("s", NodeType.START), N("llm", NodeType.LLM), api("get"), N("e", NodeType.END)], [E("s", "llm"), E("llm", "get"), E("get", "e")])
    report = analyse_exposure(reads)
    assert report.exposures == [] and "No LLM step both reads untrusted input" in report.notes[0]


def test_no_llm_no_exposure_and_models_with_no_action_are_fine():
    none = wf([N("s", NodeType.START), api(), N("e", NodeType.END)], [E("s", "api"), E("api", "e")])
    r = analyse_exposure(none)
    assert r.exposures == [] and r.llm_steps == 0 and "no LLM steps" in r.notes[0]


def test_exposures_are_sorted_most_severe_first():
    w = wf([N("s", NodeType.START), N("l1", NodeType.LLM, "Zed"), N("t", NodeType.TOOL, "Tool"), N("l2", NodeType.LLM, "Alpha"),
            N("w", NodeType.API, "Write", config={"method": "DELETE", "url": "u"}), N("e", NodeType.END)],
           [E("s", "l1"), E("l1", "t"), E("t", "l2"), E("l2", "w"), E("w", "e")])
    assert [(x.name, x.severity) for x in analyse_exposure(w).exposures] == [("Alpha", "high"), ("Zed", "high")]


# ── HTTP ─────────────────────────────────────────────────────────────────────

def http():
    return AsyncClient(transport=ASGITransport(app=app), base_url=BASE)


@pytest.fixture
def usage():
    with patch("app.api.routes.get_usage_today", AsyncMock(return_value={})), patch("app.api.routes.increment_usage", AsyncMock()) as inc:
        yield inc


@pytest.mark.asyncio
async def test_exposure_endpoint_is_free(as_user, usage):
    as_user(APPROVED_USER)
    async with http() as c:
        res = await c.post("/api/workflows/injection-exposure", json={"workflow": rag_llm_refund().model_dump(mode="json")})
    assert res.status_code == 200 and res.json()["exposures"][0]["severity"] == "high"
    usage.assert_not_called()


@pytest.mark.asyncio
async def test_resilience_endpoint_counts_one_execution_and_honours_the_limit(as_user, usage):
    as_user(APPROVED_USER)
    body = {"workflow": unhandled().model_dump(mode="json"), "input": {}}
    async with http() as c:
        ok = await c.post("/api/workflows/resilience", json=body)
        with patch("app.api.routes.get_usage_today", AsyncMock(return_value={"executions": 10_000})), patch("app.api.routes.settings.approved_max_executions_per_day", 5):
            limited = await c.post("/api/workflows/resilience", json=body)
        invalid = await c.post("/api/workflows/resilience", json={"workflow": wf([N("s", NodeType.START)], []).model_dump(mode="json")})
    assert ok.status_code == 200 and ok.json()["summary"]["total"] == 4
    assert limited.status_code == 429 and invalid.status_code == 422
    assert usage.await_count == 1


@pytest.mark.asyncio
async def test_safety_endpoints_require_auth():
    async with http() as c:
        for path in ("injection-exposure", "resilience"):
            assert (await c.post(f"/api/workflows/{path}", json={})).status_code in (401, 403, 422)
