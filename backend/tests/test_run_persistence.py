"""Tests for persisted simulation runs (Task 42). All Supabase access is mocked."""
import json
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.core import supabase_client as sc
from app.main import app
from app.models.workflow import NodeType, Workflow, WorkflowEdge, WorkflowNode
from app.providers.base import LLMProvider
from app.schemas.simulation import ConditionMode, ExecutionTrace, HITLMode, SimulationEvaluation, SimulationSettings
from app.services import run_persistence as rp
from app.services.simulator import _paused_store, simulate
from tests.conftest import APPROVED_USER

BASE = "http://test"


def N(id, type, name=None, **kw):
    return WorkflowNode(id=id, type=type, name=name or id, **kw)


def wf() -> Workflow:
    return Workflow(
        name="W",
        nodes=[N("s", NodeType.START), N("l", NodeType.LLM, config={"prompt": "p"}), N("e", NodeType.END)],
        edges=[WorkflowEdge(source="s", target="l"), WorkflowEdge(source="l", target="e")],
    )


async def make_trace(workflow=None, **settings):
    s = SimulationSettings(**settings)
    return s, await simulate(workflow or wf(), {"q": "hello"}, s)


@pytest.fixture
def enabled():
    with patch("app.services.run_persistence._enabled", return_value=True):
        yield


@pytest.fixture
def db():
    with patch.object(rp.db, "insert_run", new_callable=AsyncMock) as ins, \
         patch.object(rp.db, "update_run", new_callable=AsyncMock, return_value=True) as upd, \
         patch.object(rp.db, "prune_runs", new_callable=AsyncMock) as prune:
        yield type("DB", (), {"insert": ins, "update": upd, "prune": prune})


# ── Record building and caps ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_shape():
    s, trace = await make_trace()
    rec = rp.build_run_record("u1", wf(), {"q": "hello"}, s, trace, None)
    assert rec["id"] == trace.trace_id and rec["user_id"] == "u1"
    assert rec["status"] == "complete" and rec["step_count"] == 3
    assert rec["truncated"] is False and rec["evaluation"] is None
    assert rec["trace"]["steps"][1]["output"] is not None
    assert rec["workflow"]["name"] == "W" and rec["input"] == {"q": "hello"}
    json.dumps(rec)  # JSON-serialisable


@pytest.mark.asyncio
async def test_oversized_record_drops_step_data_but_keeps_structure():
    s, trace = await make_trace()
    full = rp.build_run_record("u1", wf(), {}, s, trace, None)
    cap = len(json.dumps(full, default=str)) - 1
    rec = rp.build_run_record("u1", wf(), {"q": "x" * 10}, s, trace, None, max_bytes=cap)
    assert rec["truncated"] is True and rec["input"] == {}
    assert all(step["input"] is None and step["output"] is None for step in rec["trace"]["steps"])
    assert [st["node_id"] for st in rec["trace"]["steps"]] == ["s", "l", "e"]


@pytest.mark.asyncio
async def test_record_that_cannot_fit_is_not_stored():
    s, trace = await make_trace()
    assert rp.build_run_record("u1", wf(), {}, s, trace, None, max_bytes=100) is None


@pytest.mark.asyncio
async def test_update_patch_contains_only_changing_columns():
    _, trace = await make_trace()
    patch_ = rp.build_run_update(trace, SimulationEvaluation(score=7, summary="s"))
    assert set(patch_) == {"status", "step_count", "trace", "evaluation", "truncated"}
    assert patch_["evaluation"]["score"] == 7


# ── persist / update behaviour ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_persist_run_inserts_then_prunes_with_configured_limits(enabled, db):
    s, trace = await make_trace()
    with patch.object(rp.settings, "max_runs_per_user", 7), patch.object(rp.settings, "run_retention_days", 3):
        run_id = await rp.persist_run("u1", wf(), {}, s, trace, None)
    assert run_id == trace.trace_id
    db.insert.assert_awaited_once()
    user_id, keep, cutoff = db.prune.await_args.args
    assert (user_id, keep) == ("u1", 7) and cutoff and cutoff.startswith("20")


@pytest.mark.asyncio
async def test_persist_run_never_raises_and_returns_none_on_failure(enabled, db):
    db.insert.side_effect = httpx.ConnectError("down")
    s, trace = await make_trace()
    assert await rp.persist_run("u1", wf(), {}, s, trace, None) is None
    db.prune.assert_not_awaited()


@pytest.mark.asyncio
async def test_prune_failure_does_not_fail_persist(enabled, db):
    db.prune.side_effect = RuntimeError("boom")
    s, trace = await make_trace()
    assert await rp.persist_run("u1", wf(), {}, s, trace, None) == trace.trace_id


@pytest.mark.asyncio
async def test_disabled_without_supabase_config():
    s, trace = await make_trace()
    with patch.object(rp.db, "insert_run", new_callable=AsyncMock) as ins:
        assert await rp.persist_run("u1", wf(), {}, s, trace, None) is None   # conftest disables persistence
    ins.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_run_is_user_scoped(enabled, db):
    _, trace = await make_trace()
    assert await rp.update_run("u1", trace, None) is True
    assert db.update.await_args.args[:2] == ("u1", trace.trace_id)


# ── Simulate / resume wiring ─────────────────────────────────────────────────

def payload(workflow, **settings):
    return {"workflow": workflow.model_dump(mode="json"), "input": {"q": 1}, "settings": settings}


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_simulate_response_carries_run_id_and_stores_user_scoped_row(enabled, db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/simulate", json=payload(wf()))
    body = res.json()
    assert res.status_code == 200 and body["run_id"] == body["trace"]["trace_id"]
    stored = db.insert.await_args.args[0]
    assert stored["user_id"] == APPROVED_USER.id and stored["input"] == {"q": 1}


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_simulate_still_succeeds_when_storage_is_down(enabled, db):
    db.insert.side_effect = httpx.ConnectError("down")
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/simulate", json=payload(wf()))
    assert res.status_code == 200 and res.json()["run_id"] is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_resume_updates_the_stored_run(enabled, db):
    hitl = Workflow(
        nodes=[N("s", NodeType.START), N("h", NodeType.HITL, config={"instructions": "x"}), N("e", NodeType.END)],
        edges=[WorkflowEdge(source="s", target="h"), WorkflowEdge(source="h", target="e")],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        first = (await client.post("/api/workflows/simulate", json=payload(hitl, hitl_mode="pause"))).json()
        assert db.insert.await_args.args[0]["status"] == "paused"
        res = await client.post("/api/workflows/simulate/resume", json={
            "trace_id": first["trace"]["trace_id"], "node_id": "h", "decision": "approve"})
    assert res.json()["run_id"] == first["trace"]["trace_id"]
    user_id, run_id, patch_ = db.update.await_args.args
    assert (user_id, run_id) == (APPROVED_USER.id, first["trace"]["trace_id"])
    assert patch_["status"] == "complete" and patch_["step_count"] == 3


# ── Evaluation fallback is visible (Task 45) ─────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_llm_evaluation_failure_is_reported_not_silent():
    no_llm = Workflow(
        nodes=[N("s", NodeType.START), N("e", NodeType.END)],
        edges=[WorkflowEdge(source="s", target="e")],
    )
    from app.services.evaluator import EvaluationError
    with patch("app.api.routes.get_provider", return_value=object()), \
         patch("app.api.routes.llm_evaluate", new_callable=AsyncMock, side_effect=EvaluationError("quota")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            res = await client.post("/api/workflows/simulate", json=payload(no_llm, llm_mode="real", evaluate=True))
    ev = res.json()["evaluation"]
    assert ev["source"] == "mock" and "quota" in ev["fallback_reason"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_mock_evaluation_has_no_fallback_reason():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/simulate", json=payload(wf(), evaluate=True))
    ev = res.json()["evaluation"]
    assert ev["source"] == "mock" and ev["fallback_reason"] is None


# ── Runs API ─────────────────────────────────────────────────────────────────

def stored_row(run_id=None):
    run_id = run_id or str(uuid.uuid4())
    trace = ExecutionTrace(trace_id=run_id, workflow_id="wf", workflow_name="W", started_at="t", status="complete")
    return {
        "id": run_id, "workflow_id": "wf", "workflow_name": "W", "status": "complete", "step_count": 0,
        "truncated": False, "created_at": "2026-11-24T10:00:00+00:00",
        "settings": SimulationSettings().model_dump(mode="json"), "input": {},
        "workflow": wf().model_dump(mode="json"), "trace": trace.model_dump(mode="json"), "evaluation": None,
    }


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_list_runs_is_scoped_and_paginated():
    rows = [{k: v for k, v in stored_row().items() if k in
             {"id", "workflow_id", "workflow_name", "status", "step_count", "truncated", "created_at"}} | {"evaluation_score": "8"}]
    with patch("app.api.runs_routes.db.list_runs", new_callable=AsyncMock, return_value=rows) as lst:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            res = await client.get("/api/runs?limit=5&offset=10")
    assert res.status_code == 200
    assert res.json()["runs"][0]["evaluation_score"] == 8
    assert lst.await_args.args == (APPROVED_USER.id, 5, 10)


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
async def test_list_runs_validates_paging(query):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        assert (await client.get(f"/api/runs?{query}")).status_code == 422


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_get_run_returns_detail_and_is_scoped():
    row = stored_row()
    with patch("app.api.runs_routes.db.get_run", new_callable=AsyncMock, return_value=row) as get:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            res = await client.get(f"/api/runs/{row['id']}")
    assert res.status_code == 200 and res.json()["workflow"]["name"] == "W"
    assert get.await_args.args == (APPROVED_USER.id, row["id"])


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_get_run_not_found_and_bad_id():
    with patch("app.api.runs_routes.db.get_run", new_callable=AsyncMock, return_value=None) as get:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            assert (await client.get(f"/api/runs/{uuid.uuid4()}")).status_code == 404
            # not a UUID: rejected before it can reach a PostgREST filter
            assert (await client.get("/api/runs/x,or=(user_id.neq.1)")).status_code == 404
    assert get.await_count == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_delete_run():
    rid = str(uuid.uuid4())
    with patch("app.api.runs_routes.db.delete_run", new_callable=AsyncMock, return_value=True) as dele:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            assert (await client.delete(f"/api/runs/{rid}")).status_code == 204
    assert dele.await_args.args == (APPROVED_USER.id, rid)
    with patch("app.api.runs_routes.db.delete_run", new_callable=AsyncMock, return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            assert (await client.delete(f"/api/runs/{rid}")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [("get", "/api/runs"), ("get", f"/api/runs/{uuid.uuid4()}"), ("delete", f"/api/runs/{uuid.uuid4()}")])
async def test_runs_api_requires_auth(method, path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await getattr(client, method)(path)
    assert res.status_code in (401, 403)


# ── PostgREST requests made by the store ─────────────────────────────────────

def _client_factory(handler):
    original = httpx.AsyncClient
    return lambda *a, **k: original(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_store_requests_are_always_scoped_to_the_user():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, dict(request.url.params)))
        return httpx.Response(200, json=[{"id": "r1"}])

    with patch.object(sc.httpx, "AsyncClient", _client_factory(handler)):
        await sc.list_runs("u1", 10, 0)
        await sc.get_run("u1", "r1")
        assert await sc.delete_run("u1", "r1") is True
        assert await sc.update_run("u1", "r1", {"status": "complete"}) is True
    assert len(seen) == 4
    assert all(params["user_id"] == "eq.u1" for _, params in seen)
    assert "evaluation_score:evaluation->>score" in seen[0][1]["select"]


@pytest.mark.asyncio
async def test_prune_deletes_old_and_excess_runs():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, dict(request.url.params)))
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": "old1"}, {"id": "old2"}])
        return httpx.Response(204)

    with patch.object(sc.httpx, "AsyncClient", _client_factory(handler)):
        await sc.prune_runs("u1", 50, "2026-10-01T00:00:00+00:00")

    methods = [m for m, _ in seen]
    assert methods == ["DELETE", "GET", "DELETE"]
    assert seen[0][1]["created_at"].startswith("lt.2026-10-01") and seen[0][1]["user_id"] == "eq.u1"
    assert seen[1][1]["offset"] == "50" and seen[1][1]["order"] == "created_at.desc"
    assert seen[2][1]["id"] == "in.(old1,old2)" and seen[2][1]["user_id"] == "eq.u1"


@pytest.mark.asyncio
async def test_prune_with_nothing_stale_makes_no_delete():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        return httpx.Response(200, json=[])

    with patch.object(sc.httpx, "AsyncClient", _client_factory(handler)):
        await sc.prune_runs("u1", 50, None)
    assert seen == ["GET"]
