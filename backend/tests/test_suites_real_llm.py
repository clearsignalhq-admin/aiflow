"""Real-LLM test suites (Task 55). The model is a fake provider: no real API call is ever made."""
import asyncio
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.api import suites_routes
from app.models.workflow import NodeType, Workflow
from app.services.suite_runner import build_report, llm_use_per_case, run_case
from tests.conftest import APPROVED_USER, DEMO_USER
from tests.test_suites import E, N, FakeDB, as_user, case, client, fake, run_body  # noqa: F401  (fixtures)


class FakeProvider:
    """Stands in for the AI model; counts calls and can be told to fail."""

    def __init__(self):
        self.calls = 0
        self.fail_on: int | None = None

    async def complete_json(self, system: str, user: str) -> dict:
        self.calls += 1
        if self.fail_on == self.calls:
            raise RuntimeError("model unavailable")
        return {"answer": "42", "call": self.calls}


@pytest.fixture
def provider():
    fake_provider = FakeProvider()
    with patch("app.providers.factory.get_provider", return_value=fake_provider), \
         patch.object(suites_routes, "get_provider", return_value=fake_provider), \
         patch.object(suites_routes.settings, "approved_max_llm_requests_per_day", 0), \
         patch.object(suites_routes.settings, "demo_max_llm_requests_per_day", 20):
        yield fake_provider


def two_llm_workflow(wf_id="wf-1") -> Workflow:
    """START → LLM A → LLM B → END   (2 model calls per case)"""
    return Workflow(
        id=wf_id, name="Two models",
        nodes=[N("s", NodeType.START), N("a", NodeType.LLM, "A", config={"prompt": "first"}),
               N("b", NodeType.LLM, "B", config={"prompt": "second", "mock_output": {"pinned": True}}), N("e", NodeType.END)],
        edges=[E("s", "a"), E("a", "b"), E("b", "e")],
    )


def branching_workflow() -> Workflow:
    """One route has 1 model call, the other has 3: the estimate must use the worst route."""
    return Workflow(
        id="wf-1", name="Branches",
        nodes=[N("s", NodeType.START), N("c", NodeType.CONDITION, "Pick", config={"expression": "input.big"}),
               N("l1", NodeType.LLM, "L1"), N("l2", NodeType.LLM, "L2"), N("l3", NodeType.LLM, "L3"), N("l4", NodeType.LLM, "L4"),
               N("e", NodeType.END)],
        edges=[E("s", "c"), E("c", "l1", "false"), E("c", "l2", "true"), E("l2", "l3"), E("l3", "l4"), E("l1", "e"), E("l4", "e")],
    )


def suite_body(n=2):
    return {"name": "Real", "workflow_id": "wf-1", "cases": [
        {"name": f"c{i}", "input": {"q": i}, "assertions": [{"type": "exists", "path": "result.answer"}]} for i in range(n)]}


def real_body(wf=None, **extra):
    return {**run_body(wf or two_llm_workflow()), "llm_mode": "real", **extra}


async def make_suite(c, n=2):
    res = await c.post("/api/suites", json=suite_body(n))
    assert res.status_code == 201, res.text
    return res.json()["id"]


# ═══════════════ Runner ═══════════════

@pytest.mark.asyncio
async def test_real_mode_calls_the_model_for_every_llm_step_and_counts_them(provider):
    result = await run_case(two_llm_workflow(), case(assertions=[{"type": "equals", "path": "result.answer", "value": "42"}]), 0, 0, llm_mode="real")
    assert result.status == "passed" and result.llm_calls == 2 and provider.calls == 2


@pytest.mark.asyncio
async def test_a_pinned_mock_output_is_ignored_in_real_mode_but_used_in_mock_mode(provider):
    mock = await run_case(two_llm_workflow(), case(assertions=[{"type": "equals", "path": "pinned", "value": True}]), 0, 0)
    assert mock.status == "passed" and mock.llm_calls == 0 and provider.calls == 0
    real = await run_case(two_llm_workflow(), case(assertions=[{"type": "exists", "path": "pinned", "value": False}]), 0, 0, llm_mode="real")
    assert real.status == "passed" and provider.calls == 2


@pytest.mark.asyncio
async def test_a_failed_model_call_is_an_error_and_is_still_counted(provider):
    provider.fail_on = 2
    result = await run_case(two_llm_workflow(), case(), 0, 0, llm_mode="real")
    assert result.status == "error" and "model unavailable" in result.error and result.error_node_id == "b"
    assert result.llm_calls == 2                                         # both steps started, so both are charged


@pytest.mark.asyncio
async def test_a_timeout_charges_the_most_the_case_could_have_used(provider):
    async def slow(*a, **k):
        await asyncio.sleep(5)

    with patch("app.services.suite_runner.simulate", slow):
        real = await run_case(two_llm_workflow(), case(), 0, 0, timeout=0.05, llm_mode="real", timeout_llm_calls=2)
        mock = await run_case(two_llm_workflow(), case(), 0, 0, timeout=0.05, timeout_llm_calls=2)
    assert real.status == "error" and "Timed out" in real.error and real.llm_calls == 2
    assert mock.llm_calls == 0                                           # mock mode never charges model calls


def test_worst_route_decides_the_estimate():
    assert llm_use_per_case(branching_workflow()) == (3, pytest.approx(0.006))
    assert llm_use_per_case(two_llm_workflow()) == (2, pytest.approx(0.004))
    no_llm = Workflow(nodes=[N("s", NodeType.START), N("e", NodeType.END)], edges=[E("s", "e")])
    assert llm_use_per_case(no_llm) == (0, 0)


def test_cycles_fall_back_to_every_llm_step():
    wf = Workflow(nodes=[N("s", NodeType.START), N("a", NodeType.LLM), N("b", NodeType.LLM), N("e", NodeType.END)],
                  edges=[E("s", "a"), E("a", "b"), E("b", "a"), E("b", "e")])
    assert llm_use_per_case(wf)[0] in (2,)


def test_report_totals_model_calls():
    results = [{"status": "passed", "path": [], "edges_taken": [], "llm_calls": 2}, {"status": "failed", "path": [], "edges_taken": [], "llm_calls": 3},
               {"status": "error", "path": [], "edges_taken": []}]
    assert build_report(two_llm_workflow().model_dump(mode="json"), 3, results).llm_calls == 5


# ═══════════════ Estimate endpoint ═══════════════

@pytest.mark.asyncio
async def test_estimate_for_mock_and_real(client, fake, provider):
    async with client as c:
        sid = await make_suite(c, 3)
        mock = (await c.post(f"/api/suites/{sid}/runs/estimate", json=run_body(two_llm_workflow()))).json()
        assert (mock["llm_mode"], mock["llm_calls_max"], mock["cost_usd_max"], mock["allowed"]) == ("mock", 0, 0, True)
        assert mock["executions_needed"] == 3 and mock["executions_remaining"] is None and mock["warnings"] == []

        real = (await c.post(f"/api/suites/{sid}/runs/estimate", json=real_body())).json()
        assert real["llm_calls_per_case_max"] == 2 and real["llm_calls_max"] == 6
        assert real["cost_usd_max"] == pytest.approx(0.012) and real["allowed"] is True and real["reason"] is None
        assert any("differ between runs" in w for w in real["warnings"])


@pytest.mark.asyncio
async def test_estimate_does_not_reserve_or_charge_anything(client, fake, provider):
    async with client as c:
        sid = await make_suite(c, 2)
        await c.post(f"/api/suites/{sid}/runs/estimate", json=real_body())
    assert fake.usage == {} and fake.runs == {} and provider.calls == 0


@pytest.mark.asyncio
async def test_estimate_warns_about_many_calls_and_about_workflows_without_models(client, fake, provider):
    many = Workflow(id="wf-1", nodes=[N("s", NodeType.START), *[N(f"l{i}", NodeType.LLM) for i in range(6)], N("e", NodeType.END)],
                    edges=[E(a, b) for a, b in zip(["s", *[f"l{i}" for i in range(6)]], [*[f"l{i}" for i in range(6)], "e"])])
    plain = Workflow(id="wf-1", nodes=[N("s", NodeType.START), N("e", NodeType.END)], edges=[E("s", "e")])
    async with client as c:
        sid = await make_suite(c, 1)
        assert any("6 model calls" in w for w in (await c.post(f"/api/suites/{sid}/runs/estimate", json=real_body(many))).json()["warnings"])
        assert any("no AI model steps" in w for w in (await c.post(f"/api/suites/{sid}/runs/estimate", json=real_body(plain))).json()["warnings"])


@pytest.mark.asyncio
async def test_estimate_reports_why_a_run_is_blocked_without_failing(client, fake, as_user, provider):
    async with client as c:
        sid = await make_suite(c, 4)
        with patch.object(suites_routes.settings, "approved_max_llm_requests_per_day", 10):
            fake.usage[APPROVED_USER.id] = 0
            fake.llm_usage[APPROVED_USER.id] = 5                        # 5 left, the run could use 8
            est = await c.post(f"/api/suites/{sid}/runs/estimate", json=real_body())
        body = est.json()
        assert est.status_code == 200 and body["allowed"] is False and body["llm_requests_remaining"] == 5
        assert "up to 8 AI model call(s) but only 5 of your daily 10 remain" in body["reason"]


# ═══════════════ Creating a real run ═══════════════

@pytest.mark.asyncio
async def test_creating_a_real_run_records_the_mode(client, fake, provider):
    async with client as c:
        sid = await make_suite(c, 2)
        run = (await c.post(f"/api/suites/{sid}/runs", json=real_body())).json()
        assert run["llm_mode"] == "real" and fake.runs[run["id"]]["llm_mode"] == "real"
        mock = (await c.post(f"/api/suites/{sid}/runs", json=run_body(two_llm_workflow()))).json()
        assert mock["llm_mode"] == "mock"
        assert provider.calls == 0                                       # creating a run costs nothing


@pytest.mark.asyncio
@pytest.mark.parametrize("setup,status,fragment", [
    ("too_many_cases", 422, "at most 20 cases"),
    ("no_provider", 503, "No AI model is configured"),
    ("llm_allowance", 429, "AI model call(s)"),
    ("exec_allowance", 429, "simulation(s)"),
])
async def test_blocked_real_runs_are_refused_with_the_reason(client, fake, provider, setup, status, fragment):
    async with client as c:
        sid = await make_suite(c, 21 if setup == "too_many_cases" else 4)
        cm = {
            "too_many_cases": patch.object(suites_routes.settings, "real_suite_max_cases", 20),
            "no_provider": patch.object(suites_routes, "get_provider", side_effect=RuntimeError("no key")),
            "llm_allowance": patch.object(suites_routes.settings, "approved_max_llm_requests_per_day", 7),
            "exec_allowance": patch.object(suites_routes.settings, "approved_max_executions_per_day", 3),
        }[setup]
        with cm:
            res = await c.post(f"/api/suites/{sid}/runs", json=real_body())
        assert res.status_code == status and fragment in res.json()["detail"]
        assert fake.runs == {}                                           # nothing was created


@pytest.mark.asyncio
async def test_mock_runs_are_not_subject_to_the_real_run_limits(client, fake, provider):
    async with client as c:
        sid = await make_suite(c, 21)
        with patch.object(suites_routes.settings, "approved_max_llm_requests_per_day", 1), \
             patch.object(suites_routes, "get_provider", side_effect=RuntimeError("no key")):
            res = await c.post(f"/api/suites/{sid}/runs", json=run_body(two_llm_workflow()))
        assert res.status_code == 201


@pytest.mark.asyncio
async def test_demo_accounts_are_limited_by_their_small_llm_allowance(client, fake, as_user, provider):
    async with client as c:
        as_user(DEMO_USER)
        ok = await make_suite(c, 10)                                     # 10 cases × 2 calls = 20 = the demo allowance
        assert (await c.post(f"/api/suites/{ok}/runs", json=real_body())).status_code == 201
        fake.llm_usage[DEMO_USER.id] = 1
        res = await c.post(f"/api/suites/{ok}/runs", json=real_body())
        assert res.status_code == 429 and "only 19 of your daily 20 remain" in res.json()["detail"]


# ═══════════════ Executing a real run ═══════════════

@pytest.mark.asyncio
async def test_real_run_charges_executions_and_model_calls_and_reports_them(client, fake, provider):
    async with client as c:
        sid = await make_suite(c, 3)
        run = (await c.post(f"/api/suites/{sid}/runs", json=real_body())).json()
        for ref in run["cases"]:
            res = await c.post(f"/api/suite-runs/{run['id']}/cases/{ref['id']}/run")
            assert res.status_code == 200 and res.json()["status"] == "passed" and res.json()["llm_calls"] == 2

        detail = (await c.get(f"/api/suite-runs/{run['id']}")).json()
        assert detail["status"] == "complete" and detail["llm_mode"] == "real"
        assert detail["report"]["llm_calls"] == 6 and detail["report"]["pass_rate"] == 1.0
    assert provider.calls == 6
    assert fake.usage[APPROVED_USER.id] == 3 and fake.llm_usage[APPROVED_USER.id] == 6


@pytest.mark.asyncio
async def test_repeating_a_case_does_not_call_the_model_or_charge_again(client, fake, provider):
    async with client as c:
        sid = await make_suite(c, 1)
        run = (await c.post(f"/api/suites/{sid}/runs", json=real_body())).json()
        url = f"/api/suite-runs/{run['id']}/cases/{run['cases'][0]['id']}/run"
        first = (await c.post(url)).json()
        again = (await c.post(url)).json()
    assert first == again and provider.calls == 2 and fake.llm_usage[APPROVED_USER.id] == 2


@pytest.mark.asyncio
async def test_a_failing_model_makes_an_error_result_and_the_run_continues(client, fake, provider):
    provider.fail_on = 2                                                  # the second call overall: case 0's second step
    async with client as c:
        sid = await make_suite(c, 2)
        run = (await c.post(f"/api/suites/{sid}/runs", json=real_body())).json()
        first = (await c.post(f"/api/suite-runs/{run['id']}/cases/{run['cases'][0]['id']}/run")).json()
        second = (await c.post(f"/api/suite-runs/{run['id']}/cases/{run['cases'][1]['id']}/run")).json()
        assert first["status"] == "error" and "model unavailable" in first["error"] and first["llm_calls"] == 2
        assert second["status"] == "passed"
        assert (await c.get(f"/api/suite-runs/{run['id']}")).json()["status"] == "complete"
    assert fake.llm_usage[APPROVED_USER.id] == 4                          # the failed case is charged too


@pytest.mark.asyncio
async def test_the_allowance_is_rechecked_before_every_case(client, fake, provider):
    async with client as c:
        sid = await make_suite(c, 2)
        run = (await c.post(f"/api/suites/{sid}/runs", json=real_body())).json()
        with patch.object(suites_routes.settings, "approved_max_llm_requests_per_day", 3):
            await c.post(f"/api/suite-runs/{run['id']}/cases/{run['cases'][0]['id']}/run")        # uses 2 of 3
            res = await c.post(f"/api/suite-runs/{run['id']}/cases/{run['cases'][1]['id']}/run")  # could use 2 more
        assert res.status_code == 429 and "daily AI request limit (3)" in res.json()["detail"]
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_a_provider_that_disappears_mid_run_stops_the_next_case(client, fake, provider):
    async with client as c:
        sid = await make_suite(c, 2)
        run = (await c.post(f"/api/suites/{sid}/runs", json=real_body())).json()
        with patch.object(suites_routes, "get_provider", side_effect=RuntimeError("no key")):
            res = await c.post(f"/api/suite-runs/{run['id']}/cases/{run['cases'][0]['id']}/run")
        assert res.status_code == 503


@pytest.mark.asyncio
async def test_mock_runs_never_touch_the_model_or_the_llm_allowance(client, fake, provider):
    async with client as c:
        sid = await make_suite(c, 2)
        run = (await c.post(f"/api/suites/{sid}/runs", json=run_body(two_llm_workflow()))).json()
        for ref in run["cases"]:
            res = (await c.post(f"/api/suite-runs/{run['id']}/cases/{ref['id']}/run")).json()
            assert res["llm_calls"] == 0
    assert provider.calls == 0 and fake.llm_usage == {} and fake.usage[APPROVED_USER.id] == 2


# ═══════════════ Migration ═══════════════

def test_llm_mode_migration_matches_schema_sql():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "supabase"
    mig = (root / "update_202611241700.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    schema = (root / "schema.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "add column if not exists llm_mode text not null default 'mock'" in mig
    assert "check (llm_mode in ('mock', 'real'))" in mig
    assert "llm_mode    text        not null default 'mock' check (llm_mode in ('mock', 'real'))" in schema
