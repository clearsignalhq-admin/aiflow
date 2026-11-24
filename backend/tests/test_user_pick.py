"""Tests for user-pick CONDITION pauses (Task 43) and the end-to-end HITL pause/resume API path."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.workflow import NodeType, Workflow, WorkflowEdge, WorkflowNode
from app.schemas.simulation import ConditionMode, HITLMode, SimulationSettings
from app.services.simulator import (
    InvalidResumeError,
    SimulationError,
    _paused_store,
    resume_simulation,
    simulate,
)

BASE = "http://test"


def N(id, type, name=None, **kw):
    return WorkflowNode(id=id, type=type, name=name or id, **kw)


def E(source, target, condition=None):
    return WorkflowEdge(source=source, target=target, condition=condition)


def branching(extra_after=False) -> Workflow:
    """START → CONDITION → (approve → API → END_A | reject → END_B)"""
    return Workflow(
        name="Pick",
        nodes=[
            N("s", NodeType.START), N("c", NodeType.CONDITION, "Decide", config={"expression": "x"}),
            N("api", NodeType.TRANSFORM, "Step"), N("ea", NodeType.END, "A"), N("eb", NodeType.END, "B"),
        ],
        edges=[E("s", "c"), E("c", "api", "yes"), E("c", "eb", "no"), E("api", "ea")],
    )


def pick() -> SimulationSettings:
    return SimulationSettings(condition_mode=ConditionMode.USER_PICK)


@pytest.fixture(autouse=True)
def _clean_store():
    _paused_store.clear()
    yield
    _paused_store.clear()


@pytest.mark.asyncio
async def test_pause_exposes_options_and_waiting_step():
    trace = await simulate(branching(), {"x": 1}, pick())
    assert trace.status == "paused"
    assert trace.trace_id in _paused_store
    cond = next(s for s in trace.steps if s.node_id == "c")
    assert cond.status.value == "waiting"
    assert cond.output == {"x": 1}
    labels = {o.target_id: (o.target_name, o.label) for o in trace.pending_choice.options}
    assert labels == {"api": ("Step", "yes"), "eb": ("B", "no")}


@pytest.mark.asyncio
async def test_choose_continues_only_the_chosen_branch():
    trace = await simulate(branching(), {"x": 1}, pick())
    done = await resume_simulation(trace.trace_id, "c", "choose", "api")
    assert done.status == "complete"
    assert done.pending_choice is None
    ids = [s.node_id for s in done.steps]
    assert ids == ["s", "c", "api", "ea"]            # eb never ran
    cond = next(s for s in done.steps if s.node_id == "c")
    assert cond.status.value == "success" and any("yes" in w for w in cond.warnings)
    assert trace.trace_id not in _paused_store


@pytest.mark.asyncio
async def test_choose_the_other_branch():
    trace = await simulate(branching(), {}, pick())
    done = await resume_simulation(trace.trace_id, "c", "choose", "eb")
    assert [s.node_id for s in done.steps] == ["s", "c", "eb"]


@pytest.mark.asyncio
@pytest.mark.parametrize("decision,target", [("approve", None), ("choose", None), ("choose", "nope"), ("choose", "s")])
async def test_invalid_resume_is_rejected_and_retryable(decision, target):
    trace = await simulate(branching(), {}, pick())
    with pytest.raises(InvalidResumeError):
        await resume_simulation(trace.trace_id, "c", decision, target)
    assert trace.trace_id in _paused_store           # still paused; caller can retry
    done = await resume_simulation(trace.trace_id, "c", "choose", "api")
    assert done.status == "complete"


@pytest.mark.asyncio
async def test_hitl_pause_rejects_choose():
    wf = Workflow(
        nodes=[N("s", NodeType.START), N("h", NodeType.HITL, config={"instructions": "x"}), N("e", NodeType.END)],
        edges=[E("s", "h"), E("h", "e")],
    )
    trace = await simulate(wf, {}, SimulationSettings(hitl_mode=HITLMode.PAUSE))
    with pytest.raises(InvalidResumeError):
        await resume_simulation(trace.trace_id, "h", "choose", "e")


@pytest.mark.asyncio
async def test_wrong_node_id_is_reported():
    trace = await simulate(branching(), {}, pick())
    with pytest.raises(SimulationError, match="not the paused condition node"):
        await resume_simulation(trace.trace_id, "zzz", "choose", "api")


@pytest.mark.asyncio
async def test_single_branch_does_not_pause():
    wf = Workflow(
        nodes=[N("s", NodeType.START), N("c", NodeType.CONDITION, config={"expression": "x"}), N("e", NodeType.END)],
        edges=[E("s", "c"), E("c", "e", "only")],
    )
    trace = await simulate(wf, {}, pick())
    assert trace.status == "complete" and trace.pending_choice is None


@pytest.mark.asyncio
async def test_two_pauses_in_one_run():
    """A user-pick condition followed by a HITL pause: both resume paths work in sequence."""
    wf = Workflow(
        nodes=[
            N("s", NodeType.START), N("c", NodeType.CONDITION, config={"expression": "x"}),
            N("h", NodeType.HITL, config={"instructions": "ok?"}), N("e1", NodeType.END, "E1"), N("e2", NodeType.END, "E2"),
        ],
        edges=[E("s", "c"), E("c", "h", "a"), E("c", "e2", "b"), E("h", "e1")],
    )
    settings = SimulationSettings(condition_mode=ConditionMode.USER_PICK, hitl_mode=HITLMode.PAUSE)
    t = await simulate(wf, {}, settings)
    assert t.pending_choice and t.pending_choice.node_id == "c"
    t = await resume_simulation(t.trace_id, "c", "choose", "h")
    assert t.status == "paused" and t.pending_choice is None
    assert next(s for s in t.steps if s.node_id == "h").status.value == "waiting"
    t = await resume_simulation(t.trace_id, "h", "approve")
    assert t.status == "complete" and [s.node_id for s in t.steps][-1] == "e1"


# ── API level (also proves the HITL pause path end to end) ───────────────────

def _payload(workflow: Workflow, **settings):
    return {"workflow": workflow.model_dump(mode="json"), "input": {}, "settings": settings}


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_api_user_pick_pause_then_choose():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/simulate", json=_payload(branching(), condition_mode="user-pick"))
        assert res.status_code == 200
        trace = res.json()["trace"]
        assert trace["status"] == "paused" and len(trace["pending_choice"]["options"]) == 2

        bad = await client.post("/api/workflows/simulate/resume", json={
            "trace_id": trace["trace_id"], "node_id": "c", "decision": "choose", "edge_target": "nope"})
        assert bad.status_code == 422

        ok = await client.post("/api/workflows/simulate/resume", json={
            "trace_id": trace["trace_id"], "node_id": "c", "decision": "choose", "edge_target": "api"})
        assert ok.status_code == 200 and ok.json()["trace"]["status"] == "complete"

        gone = await client.post("/api/workflows/simulate/resume", json={
            "trace_id": trace["trace_id"], "node_id": "c", "decision": "choose", "edge_target": "api"})
        assert gone.status_code == 404


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_api_hitl_pause_resume_end_to_end():
    wf = Workflow(
        nodes=[N("s", NodeType.START), N("h", NodeType.HITL, "Review", config={"instructions": "ok?"}), N("e", NodeType.END)],
        edges=[E("s", "h"), E("h", "e")],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/simulate", json=_payload(wf, hitl_mode="pause"))
        trace = res.json()["trace"]
        assert trace["status"] == "paused"
        assert [s["status"] for s in trace["steps"]] == ["success", "waiting"]

        res = await client.post("/api/workflows/simulate/resume", json={
            "trace_id": trace["trace_id"], "node_id": "h", "decision": "reject"})
        assert res.status_code == 200
        done = res.json()["trace"]
        assert done["status"] == "complete"
        hitl = next(s for s in done["steps"] if s["node_id"] == "h")
        assert hitl["status"] == "success" and hitl["output"]["approved"] is False
        assert done["steps"][-1]["node_id"] == "e"
