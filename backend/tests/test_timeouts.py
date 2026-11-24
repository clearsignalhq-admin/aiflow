"""Tests for the request time budget (Task 48): every guard must fire before API Gateway's 30 s cut-off."""
import asyncio
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import routes
from app.core.config import Settings
from app.main import app
from app.models.workflow import NodeType, Workflow, WorkflowEdge, WorkflowNode
from app.schemas.simulation import SimulationEvaluation
from app.services.evaluator import mock_evaluate

BASE = "http://test"
GATEWAY_LIMIT = 30.0

pytestmark = pytest.mark.usefixtures("override_approved_user")


def N(id, type, name=None, **kw):
    return WorkflowNode(id=id, type=type, name=name or id, **kw)


def wf() -> Workflow:
    return Workflow(
        name="W", nodes=[N("s", NodeType.START), N("e", NodeType.END)], edges=[WorkflowEdge(source="s", target="e")],
    )


def sim_payload(**settings):
    return {"workflow": wf().model_dump(mode="json"), "input": {}, "settings": settings}


async def post(path, body):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        return await client.post(path, json=body)


async def slow(*_a, **_k):
    await asyncio.sleep(5)


# ── Configuration invariants ─────────────────────────────────────────────────

def test_default_guards_are_all_shorter_than_the_gateway_limit():
    s = Settings()
    assert s.simulation_timeout_seconds < s.request_budget_seconds < GATEWAY_LIMIT
    assert s.llm_timeout_seconds < GATEWAY_LIMIT
    assert s.simulation_timeout_seconds + s.persist_reserve_seconds <= s.request_budget_seconds


def test_lambda_timeout_does_not_exceed_the_gateway_limit():
    template = (Path(__file__).resolve().parents[2] / "template.yaml").read_text(encoding="utf-8")
    match = re.search(r"^\s+Timeout:\s*(\d+)", template, re.M)
    assert match and int(match.group(1)) <= GATEWAY_LIMIT


# ── Simulate / resume ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_simulate_timeout_is_a_clear_504():
    with patch.object(routes, "simulate", slow), patch.object(routes.settings, "simulation_timeout_seconds", 0.05):
        res = await post("/api/workflows/simulate", sim_payload())
    assert res.status_code == 504
    assert "timed out after 0.05s" in res.json()["detail"] and "mock mode" in res.json()["detail"]


@pytest.mark.asyncio
async def test_a_timed_out_simulation_does_not_count_as_an_execution():
    with patch.object(routes, "simulate", slow), patch.object(routes.settings, "simulation_timeout_seconds", 0.05), \
         patch.object(routes, "increment_usage", new_callable=AsyncMock) as inc:
        await post("/api/workflows/simulate", sim_payload())
    inc.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_budget_caps_the_simulation_timeout():
    with patch.object(routes, "simulate", slow), \
         patch.object(routes.settings, "simulation_timeout_seconds", 25.0), \
         patch.object(routes.settings, "request_budget_seconds", 0.05):
        res = await post("/api/workflows/simulate", sim_payload())
    assert res.status_code == 504
    seconds = float(re.search(r"after ([\d.]+)s", res.json()["detail"]).group(1))
    assert 0 < seconds <= 0.05           # the 0.05 s budget, not the 25 s simulation limit


@pytest.mark.asyncio
async def test_resume_timeout_is_a_clear_504():
    with patch.object(routes, "resume_simulation", slow), patch.object(routes.settings, "simulation_timeout_seconds", 0.05):
        res = await post("/api/workflows/simulate/resume", {"trace_id": "t", "node_id": "n", "decision": "approve"})
    assert res.status_code == 504 and "Resuming timed out" in res.json()["detail"]


# ── generate / chat ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("path,body,target", [
    ("/api/workflows/generate", {"description": "d"}, "generate_workflow"),
    ("/api/workflows/chat", {"messages": [{"role": "user", "content": "hi"}]}, "chat_workflow_service"),
])
async def test_llm_calls_time_out_with_a_clear_504(path, body, target):
    with patch.object(routes, "get_provider", return_value=object()), \
         patch.object(routes, target, slow), \
         patch.object(routes.settings, "llm_timeout_seconds", 0.05), \
         patch.object(routes, "increment_usage", new_callable=AsyncMock) as inc:
        res = await post(path, body)
    assert res.status_code == 504 and "AI request timed out" in res.json()["detail"]
    inc.assert_not_awaited()                                 # a failed call is not billed


# ── Evaluation inside the budget ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_evaluation_timeout_falls_back_to_mock_with_a_reason():
    # real-LLM mode, but no LLM nodes in the workflow, so only the evaluation uses the provider
    with patch.object(routes, "get_provider", return_value=object()), patch.object(routes, "llm_evaluate", slow), \
         patch.object(routes.settings, "request_budget_seconds", 2.5), \
         patch.object(routes.settings, "persist_reserve_seconds", 0.0), \
         patch.object(routes.settings, "min_llm_evaluation_seconds", 0.1):
        res = await post("/api/workflows/simulate", sim_payload(llm_mode="real", evaluate=True))
    body = res.json()
    assert res.status_code == 200 and body["trace"]["status"] == "complete"
    assert body["evaluation"]["source"] == "mock" and "timed out" in body["evaluation"]["fallback_reason"]


@pytest.mark.asyncio
async def test_llm_evaluation_is_skipped_when_no_time_is_left():
    llm = AsyncMock()
    with patch.object(routes, "get_provider", return_value=object()), patch.object(routes, "llm_evaluate", llm), \
         patch.object(routes.settings, "request_budget_seconds", 2.0), \
         patch.object(routes.settings, "persist_reserve_seconds", 2.0):
        res = await post("/api/workflows/simulate", sim_payload(llm_mode="real", evaluate=True))
    llm.assert_not_awaited()
    assert "not enough time" in res.json()["evaluation"]["fallback_reason"]


@pytest.mark.asyncio
async def test_llm_evaluation_within_budget_is_used_and_billed():
    fake = SimulationEvaluation(score=9, summary="great", source="llm")
    with patch.object(routes, "get_provider", return_value=object()), \
         patch.object(routes, "llm_evaluate", AsyncMock(return_value=fake)), \
         patch.object(routes, "increment_usage", new_callable=AsyncMock) as inc:
        res = await post("/api/workflows/simulate", sim_payload(llm_mode="real", evaluate=True))
    ev = res.json()["evaluation"]
    assert ev["score"] == 9 and ev["source"] == "llm" and ev["fallback_reason"] is None
    assert [c.args[1] for c in inc.await_args_list] == ["executions", "llm_requests"]


def test_mock_evaluate_still_has_no_fallback_reason():
    from app.schemas.simulation import ExecutionTrace
    ev = mock_evaluate(wf(), ExecutionTrace(workflow_id="w", workflow_name="W", started_at="t"))
    assert ev.fallback_reason is None
