"""Tests for durable pause/resume (Task 46): a paused run can be resumed by a different process."""
import copy
import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.workflow import NodeType, Workflow, WorkflowEdge, WorkflowNode
from app.schemas.simulation import ConditionMode, ExecutionTrace, HITLMode, SimulationSettings
from app.services import run_persistence as rp
from app.services import simulator as sim
from app.services.simulator import _paused_store, export_paused_state, restore_paused_state, simulate
from tests.conftest import APPROVED_USER

BASE = "http://test"


def N(id, type, name=None, **kw):
    return WorkflowNode(id=id, type=type, name=name or id, **kw)


def E(s, t, c=None):
    return WorkflowEdge(source=s, target=t, condition=c)


def hitl_wf() -> Workflow:
    """START → LLM → HITL → API → END  (data must survive the pause)"""
    return Workflow(
        name="H",
        nodes=[N("s", NodeType.START), N("l", NodeType.LLM, config={"prompt": "p"}), N("h", NodeType.HITL, config={"instructions": "x"}),
               N("a", NodeType.API, config={"method": "GET", "url": "u"}), N("e", NodeType.END)],
        edges=[E("s", "l"), E("l", "h"), E("h", "a"), E("a", "e")],
    )


def pick_wf() -> Workflow:
    return Workflow(
        name="P",
        nodes=[N("s", NodeType.START), N("c", NodeType.CONDITION, config={"expression": "x"}),
               N("t1", NodeType.TRANSFORM, "T1"), N("t2", NodeType.TRANSFORM, "T2"), N("e", NodeType.END)],
        edges=[E("s", "c"), E("c", "t1", "a"), E("c", "t2", "b"), E("t1", "e"), E("t2", "e")],
    )


@pytest.fixture(autouse=True)
def _clean():
    _paused_store.clear()
    yield
    _paused_store.clear()


def stored_row(trace, workflow, settings, continuation):
    """What the database would return for the run (JSON round trip, as Supabase does)."""
    return json.loads(json.dumps({
        "id": trace.trace_id, "status": trace.status,
        "trace": trace.model_dump(mode="json"), "workflow": workflow.model_dump(mode="json"),
        "settings": settings.model_dump(mode="json"), "continuation": continuation,
    }))


# ── export / restore ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_is_json_serialisable_and_none_when_not_paused():
    s = SimulationSettings(hitl_mode=HITLMode.PAUSE)
    trace = await simulate(hitl_wf(), {"q": 1}, s)
    cont = export_paused_state(trace.trace_id)
    assert json.loads(json.dumps(cont)) == cont
    assert cont["kind"] == "hitl" and cont["paused_node_id"] == "h" and set(cont["visited"]) == {"s", "l", "h"}
    assert export_paused_state("unknown") is None
    done = await simulate(hitl_wf(), {}, SimulationSettings())
    assert export_paused_state(done.trace_id) is None


@pytest.mark.asyncio
async def test_hitl_resume_after_the_memory_store_is_lost():
    s = SimulationSettings(hitl_mode=HITLMode.PAUSE)
    wf = hitl_wf()
    trace = await simulate(wf, {"q": 1}, s)
    row = stored_row(trace, wf, s, export_paused_state(trace.trace_id))

    _paused_store.clear()                                    # a different process: nothing in memory
    assert await_restore(row)
    done = await sim.resume_simulation(trace.trace_id, "h", "approve")
    assert done.status == "complete"
    assert [x.node_id for x in done.steps] == ["s", "l", "h", "a", "e"]


def await_restore(row) -> bool:
    return restore_paused_state(
        ExecutionTrace.model_validate(row["trace"]), Workflow.model_validate(row["workflow"]),
        SimulationSettings.model_validate(row["settings"]), row["continuation"],
    )


@pytest.mark.asyncio
async def test_user_pick_resume_after_restore_keeps_branch_data_even_if_step_data_was_trimmed():
    s = SimulationSettings(condition_mode=ConditionMode.USER_PICK)
    wf = pick_wf()
    trace = await simulate(wf, {"x": 42}, s)
    row = stored_row(trace, wf, s, export_paused_state(trace.trace_id))
    for step in row["trace"]["steps"]:           # simulate the size-cap truncation
        step["input"] = None
        step["output"] = None

    _paused_store.clear()
    assert await_restore(row)
    done = await sim.resume_simulation(trace.trace_id, "c", "choose", "t2")
    assert [x.node_id for x in done.steps] == ["s", "c", "t2", "e"]
    t2 = next(x for x in done.steps if x.node_id == "t2")
    assert t2.input == {"x": 42}                 # continuation_output, not the trimmed step output


@pytest.mark.asyncio
async def test_restored_state_still_validates_the_choice():
    s = SimulationSettings(condition_mode=ConditionMode.USER_PICK)
    wf = pick_wf()
    trace = await simulate(wf, {}, s)
    row = stored_row(trace, wf, s, export_paused_state(trace.trace_id))
    _paused_store.clear()
    assert await_restore(row)
    with pytest.raises(sim.InvalidResumeError):
        await sim.resume_simulation(trace.trace_id, "c", "choose", "e")


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate", [
    lambda c: None,
    lambda c: "not a dict",
    lambda c: {**c, "v": 99},
    lambda c: {**c, "kind": "other"},
    lambda c: {**c, "paused_node_id": "ghost"},
    lambda c: {**c, "queue": [["ghost", {}]]},
    lambda c: {**c, "queue": [["s", "notadict"]]},
    lambda c: {**c, "queue": "nope"},
    lambda c: {**c, "visited": [1, 2]},
    lambda c: {**c, "visited": ["ghost"]},
    lambda c: {**c, "choice_targets": ["ghost"]},
    lambda c: {**c, "condition_output": "x"},
])
async def test_corrupt_continuations_are_refused(mutate):
    s = SimulationSettings(hitl_mode=HITLMode.PAUSE)
    wf = hitl_wf()
    trace = await simulate(wf, {}, s)
    cont = copy.deepcopy(export_paused_state(trace.trace_id))
    row = stored_row(trace, wf, s, mutate(cont))
    _paused_store.clear()
    assert await_restore(row) is False
    assert trace.trace_id not in _paused_store


@pytest.mark.asyncio
async def test_restore_requires_a_paused_trace_with_a_waiting_step():
    s = SimulationSettings(hitl_mode=HITLMode.PAUSE)
    wf = hitl_wf()
    trace = await simulate(wf, {}, s)
    cont = export_paused_state(trace.trace_id)
    row = stored_row(trace, wf, s, cont)
    _paused_store.clear()

    complete = copy.deepcopy(row)
    complete["trace"]["status"] = "complete"
    assert await_restore(complete) is False

    no_waiting = copy.deepcopy(row)
    for step in no_waiting["trace"]["steps"]:
        step["status"] = "success"
    assert await_restore(no_waiting) is False


# ── load_paused (database path) ──────────────────────────────────────────────

@pytest.fixture
def enabled():
    with patch("app.services.run_persistence._enabled", return_value=True):
        yield


@pytest.mark.asyncio
async def test_load_paused_is_user_scoped_and_ignores_non_paused_rows(enabled):
    s = SimulationSettings(hitl_mode=HITLMode.PAUSE)
    wf = hitl_wf()
    trace = await simulate(wf, {}, s)
    row = stored_row(trace, wf, s, export_paused_state(trace.trace_id))
    _paused_store.clear()

    with patch.object(rp.db, "get_run", new_callable=AsyncMock, return_value=row) as get:
        assert await rp.load_paused("user-1", trace.trace_id) is True
        assert get.await_args.args == ("user-1", trace.trace_id)
    _paused_store.clear()

    with patch.object(rp.db, "get_run", new_callable=AsyncMock, return_value=None):
        assert await rp.load_paused("someone-else", trace.trace_id) is False
    with patch.object(rp.db, "get_run", new_callable=AsyncMock, return_value={**row, "status": "complete"}):
        assert await rp.load_paused("user-1", trace.trace_id) is False
    with patch.object(rp.db, "get_run", new_callable=AsyncMock, return_value={**row, "continuation": None}):
        assert await rp.load_paused("user-1", trace.trace_id) is False
    with patch.object(rp.db, "get_run", new_callable=AsyncMock, side_effect=RuntimeError("down")):
        assert await rp.load_paused("user-1", trace.trace_id) is False


@pytest.mark.asyncio
async def test_load_paused_disabled_without_supabase():
    with patch.object(rp.db, "get_run", new_callable=AsyncMock) as get:
        assert await rp.load_paused("u", "t") is False
    get.assert_not_awaited()


# ── End to end through the API ───────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_api_resume_works_after_a_cold_start(enabled):
    """Container A pauses and stores the run; container B (empty memory) resumes it."""
    wf = hitl_wf()
    inserted, updated = {}, {}

    async def fake_insert(record):
        inserted.update(record)

    async def fake_update(user_id, run_id, patch_):
        updated.update(patch_)
        return True

    async def fake_get(user_id, run_id):
        assert user_id == APPROVED_USER.id          # always scoped to the caller
        return copy.deepcopy(inserted) if inserted.get("id") == run_id else None

    with patch.object(rp.db, "insert_run", side_effect=fake_insert), \
         patch.object(rp.db, "update_run", side_effect=fake_update), \
         patch.object(rp.db, "get_run", side_effect=fake_get), \
         patch.object(rp.db, "prune_runs", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            res = await client.post("/api/workflows/simulate", json={
                "workflow": wf.model_dump(mode="json"), "input": {"q": 1}, "settings": {"hitl_mode": "pause"}})
            trace = res.json()["trace"]
            assert trace["status"] == "paused"
            assert inserted["continuation"]["paused_node_id"] == "h"      # stored with the run

            _paused_store.clear()                                          # ← different container

            res = await client.post("/api/workflows/simulate/resume", json={
                "trace_id": trace["trace_id"], "node_id": "h", "decision": "approve"})
            assert res.status_code == 200, res.text
            assert res.json()["trace"]["status"] == "complete"
            assert updated["status"] == "complete" and updated["continuation"] is None   # cleared


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_api_second_pause_stores_a_fresh_continuation(enabled):
    wf = Workflow(
        nodes=[N("s", NodeType.START), N("h1", NodeType.HITL, config={"instructions": "a"}),
               N("h2", NodeType.HITL, config={"instructions": "b"}), N("e", NodeType.END)],
        edges=[E("s", "h1"), E("h1", "h2"), E("h2", "e")],
    )
    updated = {}

    async def fake_update(user_id, run_id, patch_):
        updated.update(patch_)
        return True

    with patch.object(rp.db, "insert_run", new_callable=AsyncMock), \
         patch.object(rp.db, "update_run", side_effect=fake_update), \
         patch.object(rp.db, "prune_runs", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            trace = (await client.post("/api/workflows/simulate", json={
                "workflow": wf.model_dump(mode="json"), "input": {}, "settings": {"hitl_mode": "pause"}})).json()["trace"]
            res = await client.post("/api/workflows/simulate/resume", json={
                "trace_id": trace["trace_id"], "node_id": "h1", "decision": "approve"})
    assert res.json()["trace"]["status"] == "paused"
    assert updated["status"] == "paused" and updated["continuation"]["paused_node_id"] == "h2"


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_api_resume_of_unknown_run_is_404_and_does_not_leak(enabled):
    with patch.object(rp.db, "get_run", new_callable=AsyncMock, return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            res = await client.post("/api/workflows/simulate/resume", json={
                "trace_id": "00000000-0000-0000-0000-000000000000", "node_id": "h", "decision": "approve"})
    assert res.status_code == 404
