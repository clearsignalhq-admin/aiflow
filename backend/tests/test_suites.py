"""Tests for test suites: runner, report, and the HTTP API (Task 50). Supabase is replaced by an in-memory fake."""
import asyncio
import copy
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import suites_routes
from app.api.deps import get_current_user, require_approved
from app.main import app
from app.models.workflow import NodeType, Workflow, WorkflowEdge, WorkflowNode
from app.services.suite_runner import build_report, case_settings, final_output, run_case
from tests.conftest import APPROVED_USER, DEMO_USER

BASE = "http://test"


def N(id, type, name=None, **kw):
    return WorkflowNode(id=id, type=type, name=name or id, **kw)


def E(s, t, c=None):
    return WorkflowEdge(source=s, target=t, condition=c)


def routed_workflow(wf_id="wf-1") -> Workflow:
    """START → LLM(tier enum) → CONDITION → premium / basic → END"""
    return Workflow(
        id=wf_id, name="Router",
        nodes=[
            N("s", NodeType.START),
            N("l", NodeType.LLM, "Classify", config={"prompt": "p"},
              output_schema={"type": "object", "properties": {"tier": {"type": "string", "enum": ["basic", "premium"]}}}),
            N("c", NodeType.CONDITION, "Route", config={"expression": "input.tier"}),
            N("p", NodeType.TRANSFORM, "Premium"), N("b", NodeType.TRANSFORM, "Basic"), N("e", NodeType.END),
        ],
        edges=[E("s", "l"), E("l", "c"), E("c", "p", "premium"), E("c", "b", "basic"), E("p", "e"), E("b", "e")],
    )


def simple_workflow(wf_id="wf-1") -> Workflow:
    return Workflow(id=wf_id, name="Simple", nodes=[N("s", NodeType.START), N("e", NodeType.END)], edges=[E("s", "e")])


def case(name="c", **kw) -> dict:
    return {"id": kw.pop("id", str(uuid.uuid4())), "name": name, "input": {}, "assertions": [], "tags": [], "seed": None, **kw}


# ═══════════════════════════ Runner ═══════════════════════════

@pytest.mark.asyncio
async def test_case_passes_and_reports_path_and_edges():
    wf = simple_workflow()
    r = await run_case(wf, case(input={"q": "hi"}, assertions=[
        {"type": "equals", "path": "q", "value": "hi"}, {"type": "visits_node", "node_id": "e"}]), 0, 0)
    assert r.status == "passed" and r.path == ["s", "e"] and r.edges_taken == ["s→e"]
    assert r.output == {"q": "hi"} and all(a.passed for a in r.assertion_results)


@pytest.mark.asyncio
async def test_failed_assertion_fails_the_case_but_runs_the_rest():
    r = await run_case(simple_workflow(), case(input={"q": 1}, assertions=[
        {"type": "equals", "path": "q", "value": 2}, {"type": "exists", "path": "q"}]), 0, 0)
    assert r.status == "failed"
    assert [a.passed for a in r.assertion_results] == [False, True]


@pytest.mark.asyncio
async def test_case_without_assertions_passes_when_the_simulation_completes():
    assert (await run_case(simple_workflow(), case(), 0, 0)).status == "passed"


@pytest.mark.asyncio
async def test_simulation_error_is_an_error_not_a_failure():
    cyclic = Workflow(id="w", nodes=[N("s", NodeType.START), N("a", NodeType.TRANSFORM), N("e", NodeType.END)],
                      edges=[E("s", "a"), E("a", "a"), E("a", "e")])
    r = await run_case(cyclic, case(assertions=[{"type": "max_steps", "max_steps": 5}]), 0, 0)
    assert r.status == "error" and "cycle" in r.error.lower() and r.assertion_results == []


@pytest.mark.asyncio
async def test_timeout_is_an_error():
    async def slow(*a, **k):
        await asyncio.sleep(5)

    with patch("app.services.suite_runner.simulate", slow):
        r = await run_case(simple_workflow(), case(), 0, 0, timeout=0.05)
    assert r.status == "error" and "Timed out" in r.error


@pytest.mark.asyncio
async def test_unexpected_exception_does_not_escape():
    async def boom(*a, **k):
        raise RuntimeError("kaboom")

    with patch("app.services.suite_runner.simulate", boom):
        r = await run_case(simple_workflow(), case(), 0, 0)
    assert r.status == "error" and "kaboom" in r.error


@pytest.mark.asyncio
async def test_node_error_in_trace_records_the_failing_node():
    async def failing(wf, data, settings):
        from app.services.simulator import simulate as real
        trace = await real(wf, data, settings)
        trace.steps[1].status = "error"
        trace.steps[1].error = "bad node"
        trace.status = "error"
        return trace

    with patch("app.services.suite_runner.simulate", failing):
        r = await run_case(simple_workflow(), case(), 0, 0)
    assert r.status == "error" and r.error == "bad node" and r.error_node_id == "e" and r.path == ["s", "e"]


def test_seeds_use_the_case_seed_or_run_seed_plus_index():
    assert case_settings({"seed": 7}, 3, 100).seed == 7
    assert case_settings({"seed": None}, 3, 100).seed == 103
    s = case_settings({}, 0, 0)
    assert (s.llm_mode.value, s.hitl_mode.value, s.condition_mode.value, s.evaluate) == ("mock", "auto-approve", "expression", False)


@pytest.mark.asyncio
async def test_results_are_reproducible_and_seeds_change_the_branch():
    wf = routed_workflow()

    async def paths(run_seed):
        return [(await run_case(wf, case(), i, run_seed)).path for i in range(12)]

    assert await paths(0) == await paths(0)
    assert len({tuple(p) for p in await paths(0)}) == 2      # both branches are reached across seeds


@pytest.mark.asyncio
async def test_an_explicit_case_seed_pins_the_branch():
    wf = routed_workflow()
    paths = {tuple((await run_case(wf, case(seed=4), i, 999)).path) for i in range(5)}
    assert len(paths) == 1                                   # same seed, same path, whatever the index or run seed


@pytest.mark.asyncio
async def test_large_outputs_are_truncated():
    big = {"text": "x" * 20_000}
    wf = Workflow(id="w", nodes=[N("s", NodeType.START), N("e", NodeType.END)], edges=[E("s", "e")])
    r = await run_case(wf, case(input=big), 0, 0)
    assert r.output["_truncated"] is True and len(r.output["preview"]) <= 500


def test_final_output_is_the_last_end_result():
    from app.schemas.simulation import ExecutionTrace, NodeExecution
    steps = [
        NodeExecution(node_id="s", node_name="s", node_type="START", status="success", started_at="t", output={"a": 1}),
        NodeExecution(node_id="e", node_name="e", node_type="END", status="success", started_at="t", output={"result": {"ok": True}}),
    ]
    assert final_output(ExecutionTrace(workflow_id="w", workflow_name="w", started_at="t", steps=steps)) == {"ok": True}
    assert final_output(ExecutionTrace(workflow_id="w", workflow_name="w", started_at="t", steps=steps[:1])) is None


def test_build_report_pass_rate_and_coverage():
    wf = routed_workflow().model_dump(mode="json")
    results = [
        {"status": "passed", "path": ["s", "l", "c", "p", "e"], "edges_taken": ["s→l", "l→c", "c→p", "p→e"]},
        {"status": "failed", "path": ["s", "l", "c", "p", "e"], "edges_taken": ["s→l", "l→c", "c→p", "p→e"]},
        {"status": "error", "path": ["s", "l"], "edges_taken": ["s→l"], "error_node_id": "c"},
    ]
    rep = build_report(wf, 5, results)
    assert (rep.total, rep.completed, rep.passed, rep.failed, rep.errors) == (5, 3, 1, 1, 1)
    assert rep.pass_rate == pytest.approx(1 / 3, abs=1e-3)
    assert rep.coverage.node_visits["p"] == 2 and rep.coverage.node_visits["b"] == 0
    assert rep.coverage.never_visited == ["b"]
    never = {(e["source"], e["target"]) for e in rep.coverage.edges_never_taken}
    assert never == {("c", "b"), ("b", "e")}
    assert rep.coverage.edges_never_taken[0]["label"] in ("basic", None)
    assert rep.coverage.node_failures == {"s": 2, "l": 2, "c": 2, "p": 1, "e": 1}   # failed visited p/e; the error broke at c


def test_build_report_with_no_results():
    rep = build_report(simple_workflow().model_dump(mode="json"), 3, [])
    assert rep.pass_rate is None and rep.completed == 0 and rep.coverage.never_visited == ["s", "e"]


# ═══════════════════════════ In-memory fake of the DB layer ═══════════════════════════

class FakeDB:
    def __init__(self):
        self.suites, self.runs, self.results, self.usage = {}, {}, {}, {}

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    # suites
    async def list_suites(self, user_id, workflow_id):
        return [s for s in self.suites.values() if s["user_id"] == user_id and (not workflow_id or s["workflow_id"] == workflow_id)]

    async def count_suites(self, user_id):
        return len([s for s in self.suites.values() if s["user_id"] == user_id])

    async def get_suite(self, user_id, suite_id):
        s = self.suites.get(suite_id)
        return copy.deepcopy(s) if s and s["user_id"] == user_id else None

    async def insert_suite(self, record):
        row = {**copy.deepcopy(record), "id": str(uuid.uuid4()), "created_at": self._now(), "updated_at": self._now()}
        self.suites[row["id"]] = row
        return copy.deepcopy(row)

    async def update_suite(self, user_id, suite_id, patch):
        s = self.suites.get(suite_id)
        if not s or s["user_id"] != user_id:
            return None
        s.update(copy.deepcopy(patch))
        s["updated_at"] = self._now()
        return copy.deepcopy(s)

    async def delete_suite(self, user_id, suite_id):
        s = self.suites.get(suite_id)
        if not s or s["user_id"] != user_id:
            return False
        del self.suites[suite_id]
        for rid in [r for r, v in self.runs.items() if v["suite_id"] == suite_id]:
            self.runs.pop(rid)
            self.results.pop(rid, None)
        return True

    # runs
    async def insert_suite_run(self, record):
        row = {**copy.deepcopy(record), "id": str(uuid.uuid4()), "status": "running", "created_at": self._now(),
               "finished_at": None, "note": None}
        self.runs[row["id"]] = row
        return copy.deepcopy(row)

    async def get_suite_run(self, user_id, run_id):
        r = self.runs.get(run_id)
        return copy.deepcopy(r) if r and r["user_id"] == user_id else None

    async def update_suite_run(self, user_id, run_id, patch):
        r = self.runs.get(run_id)
        if not r or r["user_id"] != user_id:
            return False
        r.update(patch)
        return True

    async def list_suite_runs(self, user_id, suite_id, limit):
        rows = [r for r in self.runs.values() if r["user_id"] == user_id and r["suite_id"] == suite_id]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return [{**{k: v for k, v in r.items() if k not in ("workflow", "cases")},
                 "suite_case_results": [{"status": x["status"]} for x in self.results.get(r["id"], {}).values()]}
                for r in rows[:limit]]

    async def prune_suite_runs(self, user_id, suite_id, keep):
        rows = sorted([r for r in self.runs.values() if r["user_id"] == user_id and r["suite_id"] == suite_id],
                      key=lambda r: r["created_at"], reverse=True)
        for r in rows[keep:]:
            self.runs.pop(r["id"])
            self.results.pop(r["id"], None)

    # results
    async def list_case_results(self, user_id, run_id):
        return [copy.deepcopy(x) for x in self.results.get(run_id, {}).values() if x["user_id"] == user_id]

    async def get_case_result(self, user_id, run_id, case_id):
        x = self.results.get(run_id, {}).get(case_id)
        return copy.deepcopy(x) if x and x["user_id"] == user_id else None

    async def insert_case_result(self, record):
        bucket = self.results.setdefault(record["run_id"], {})
        if record["case_id"] in bucket:
            return False
        bucket[record["case_id"]] = copy.deepcopy(record)
        return True

    # usage
    async def get_usage_today(self, user_id):
        return {"executions": self.usage.get(user_id, 0), "llm_requests": 0}

    async def increment_usage(self, user_id, field, by=1):
        assert field == "executions"
        self.usage[user_id] = self.usage.get(user_id, 0) + by


@pytest.fixture
def fake():
    db = FakeDB()
    with patch.object(suites_routes, "db", db), \
         patch.object(suites_routes.settings, "approved_max_executions_per_day", 0), \
         patch.object(suites_routes.settings, "demo_max_executions_per_day", 10):
        yield db


@pytest.fixture
def as_user():
    def _set(user):
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[require_approved] = lambda: user
    yield _set
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_approved, None)


@pytest.fixture
def client(fake, as_user):
    as_user(APPROVED_USER)
    return AsyncClient(transport=ASGITransport(app=app), base_url=BASE)


def suite_body(n=2, wf_id="wf-1", name="My suite"):
    return {"name": name, "workflow_id": wf_id, "cases": [
        {"name": f"case {i}", "input": {"i": i}, "assertions": [{"type": "equals", "path": "i", "value": i}]} for i in range(n)]}


async def make_suite(c, **kw):
    res = await c.post("/api/suites", json=suite_body(**kw))
    assert res.status_code == 201, res.text
    return res.json()


def run_body(wf=None, seed=0):
    return {"workflow": (wf or simple_workflow()).model_dump(mode="json"), "seed": seed}


# ═══════════════════════════ Suite definitions API ═══════════════════════════

@pytest.mark.asyncio
async def test_create_get_list_update_delete(client, fake):
    async with client as c:
        created = await make_suite(c, n=3)
        assert len(created["cases"]) == 3 and all(x["id"] for x in created["cases"])
        sid = created["id"]

        listed = (await c.get("/api/suites?workflow_id=wf-1")).json()["suites"]
        assert [(s["id"], s["case_count"]) for s in listed] == [(sid, 3)]
        assert (await c.get("/api/suites?workflow_id=other")).json()["suites"] == []

        assert (await c.get(f"/api/suites/{sid}")).json()["name"] == "My suite"

        keep = created["cases"][0]
        upd = await c.put(f"/api/suites/{sid}", json={"name": "Renamed", "cases": [keep, {"name": "new", "input": {}}]})
        body = upd.json()
        assert upd.status_code == 200 and body["name"] == "Renamed" and len(body["cases"]) == 2
        assert body["cases"][0]["id"] == keep["id"]                      # ids are stable across edits
        assert fake.suites[sid]["case_count"] == 2 and body["workflow_id"] == "wf-1"

        assert (await c.delete(f"/api/suites/{sid}")).status_code == 204
        assert (await c.get(f"/api/suites/{sid}")).status_code == 404
        assert (await c.delete(f"/api/suites/{sid}")).status_code == 404


@pytest.mark.asyncio
async def test_validation_errors(client):
    async with client as c:
        bad_assertion = {"name": "s", "workflow_id": "w", "cases": [{"name": "x", "assertions": [{"type": "equals"}]}]}
        assert (await c.post("/api/suites", json=bad_assertion)).status_code == 422
        assert (await c.post("/api/suites", json={"name": "s", "cases": []})).status_code == 422        # workflow_id required
        assert (await c.post("/api/suites", json={"name": "", "workflow_id": "w"})).status_code == 422
        dup = {"name": "s", "workflow_id": "w", "cases": [{"id": "same", "name": "a"}, {"id": "same", "name": "b"}]}
        res = await c.post("/api/suites", json=dup)
        assert res.status_code == 422 and "Duplicate" in res.json()["detail"]
        huge = {"name": "s", "workflow_id": "w", "cases": [
            {"name": f"c{i}", "input": {"t": "x" * 19_000}} for i in range(30)]}
        assert (await c.post("/api/suites", json=huge)).status_code == 413


@pytest.mark.asyncio
async def test_case_caps_follow_the_tier(client, as_user):
    async with client as c:
        assert (await c.post("/api/suites", json=suite_body(n=50))).status_code == 201
        res = await c.post("/api/suites", json=suite_body(n=51))
        assert res.status_code == 422 and "at most 50" in res.json()["detail"]
        as_user(DEMO_USER)
        assert (await c.post("/api/suites", json=suite_body(n=10))).status_code == 201
        res = await c.post("/api/suites", json=suite_body(n=11))
        assert res.status_code == 422 and "at most 10" in res.json()["detail"]


@pytest.mark.asyncio
async def test_suite_count_cap(client):
    async with client as c:
        with patch.object(suites_routes.settings, "max_suites_per_user", 2):
            await make_suite(c)
            await make_suite(c)
            assert (await c.post("/api/suites", json=suite_body())).status_code == 409


@pytest.mark.asyncio
async def test_users_cannot_see_or_touch_each_others_suites(client, as_user):
    async with client as c:
        sid = (await make_suite(c))["id"]
        as_user(DEMO_USER)
        assert (await c.get(f"/api/suites/{sid}")).status_code == 404
        assert (await c.put(f"/api/suites/{sid}", json={"name": "x", "cases": []})).status_code == 404
        assert (await c.delete(f"/api/suites/{sid}")).status_code == 404
        assert (await c.post(f"/api/suites/{sid}/runs", json=run_body())).status_code == 404
        assert (await c.get("/api/suites")).json()["suites"] == []


@pytest.mark.asyncio
async def test_bad_ids_are_404_before_reaching_the_database(client, fake):
    async with client as c:
        for path in ("/api/suites/x,or=(1)", "/api/suite-runs/not-a-uuid", f"/api/suite-runs/{uuid.uuid4()}"):
            assert (await c.get(path)).status_code == 404


# ═══════════════════════════ Runs API ═══════════════════════════

@pytest.mark.asyncio
async def test_run_creation_checks(client):
    async with client as c:
        suite = await make_suite(c)
        sid = suite["id"]
        empty = await make_suite(c, n=0, name="empty")
        assert (await c.post(f"/api/suites/{empty['id']}/runs", json=run_body())).status_code == 422

        res = await c.post(f"/api/suites/{sid}/runs", json=run_body(simple_workflow("other-workflow")))
        assert res.status_code == 422 and "different workflow" in res.json()["detail"]

        cyclic = Workflow(id="wf-1", nodes=[N("s", NodeType.START), N("a", NodeType.TRANSFORM), N("e", NodeType.END)],
                          edges=[E("s", "a"), E("a", "a"), E("a", "e")])
        res = await c.post(f"/api/suites/{sid}/runs", json=run_body(cyclic))
        assert res.status_code == 422 and "cannot be simulated" in res.json()["detail"]

        ok = await c.post(f"/api/suites/{sid}/runs", json=run_body())
        assert ok.status_code == 201
        body = ok.json()
        assert body["status"] == "running" and body["case_count"] == 2 and len(body["cases"]) == 2
        assert body["results"] == [] and body["report"]["pass_rate"] is None


@pytest.mark.asyncio
async def test_full_run_executes_every_case_and_completes(client, fake):
    async with client as c:
        sid = (await make_suite(c, n=3))["id"]
        run = (await c.post(f"/api/suites/{sid}/runs", json=run_body())).json()
        for ref in run["cases"]:
            res = await c.post(f"/api/suite-runs/{run['id']}/cases/{ref['id']}/run")
            assert res.status_code == 200 and res.json()["status"] == "passed", res.text

        detail = (await c.get(f"/api/suite-runs/{run['id']}")).json()
        assert detail["status"] == "complete" and detail["finished_at"]
        assert detail["report"]["passed"] == 3 and detail["report"]["pass_rate"] == 1.0
        assert [r["case_name"] for r in detail["results"]] == ["case 0", "case 1", "case 2"]   # definition order
        assert fake.usage[APPROVED_USER.id] == 3                       # one execution per case, nothing else


@pytest.mark.asyncio
async def test_failures_are_reported_in_the_report(client):
    async with client as c:
        body = {"name": "s", "workflow_id": "wf-1", "cases": [
            {"name": "good", "input": {"v": 1}, "assertions": [{"type": "equals", "path": "v", "value": 1}]},
            {"name": "bad", "input": {"v": 1}, "assertions": [{"type": "equals", "path": "v", "value": 2, "label": "v is 2"}]}]}
        sid = (await c.post("/api/suites", json=body)).json()["id"]
        run = (await c.post(f"/api/suites/{sid}/runs", json=run_body())).json()
        for ref in run["cases"]:
            await c.post(f"/api/suite-runs/{run['id']}/cases/{ref['id']}/run")
        detail = (await c.get(f"/api/suite-runs/{run['id']}")).json()
        assert (detail["report"]["passed"], detail["report"]["failed"]) == (1, 1) and detail["report"]["pass_rate"] == 0.5
        failed = next(r for r in detail["results"] if r["status"] == "failed")
        assert failed["assertion_results"][0]["label"] == "v is 2" and "expected 2" in failed["assertion_results"][0]["message"]


@pytest.mark.asyncio
async def test_running_a_case_twice_returns_the_stored_result_without_charging_again(client, fake):
    async with client as c:
        sid = (await make_suite(c, n=2))["id"]
        run = (await c.post(f"/api/suites/{sid}/runs", json=run_body())).json()
        ref = run["cases"][0]
        first = (await c.post(f"/api/suite-runs/{run['id']}/cases/{ref['id']}/run")).json()
        again = (await c.post(f"/api/suite-runs/{run['id']}/cases/{ref['id']}/run")).json()
        assert first == again and fake.usage[APPROVED_USER.id] == 1


@pytest.mark.asyncio
async def test_unknown_case_and_cancel(client, fake):
    async with client as c:
        sid = (await make_suite(c, n=2))["id"]
        run = (await c.post(f"/api/suites/{sid}/runs", json=run_body())).json()
        assert (await c.post(f"/api/suite-runs/{run['id']}/cases/{uuid.uuid4()}/run")).status_code == 404

        await c.post(f"/api/suite-runs/{run['id']}/cases/{run['cases'][0]['id']}/run")
        cancelled = (await c.post(f"/api/suite-runs/{run['id']}/cancel")).json()
        assert cancelled["status"] == "cancelled" and cancelled["finished_at"]

        res = await c.post(f"/api/suite-runs/{run['id']}/cases/{run['cases'][1]['id']}/run")
        assert res.status_code == 409 and "cancelled" in res.json()["detail"]
        # the case that already ran can still be read back
        assert (await c.post(f"/api/suite-runs/{run['id']}/cases/{run['cases'][0]['id']}/run")).status_code == 200
        assert (await c.post(f"/api/suite-runs/{run['id']}/cancel")).json()["status"] == "cancelled"   # idempotent


@pytest.mark.asyncio
async def test_stale_running_jobs_are_marked_failed(client, fake):
    async with client as c:
        sid = (await make_suite(c, n=2))["id"]
        run = (await c.post(f"/api/suites/{sid}/runs", json=run_body())).json()
        fake.runs[run["id"]]["created_at"] = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
        detail = (await c.get(f"/api/suite-runs/{run['id']}")).json()
        assert detail["status"] == "failed" and "within 15 minutes" in detail["note"]
        assert fake.runs[run["id"]]["status"] == "failed"                 # persisted, not just displayed


@pytest.mark.asyncio
async def test_daily_allowance_is_shared_and_enforced(client, as_user, fake):
    async with client as c:
        as_user(DEMO_USER)                                               # demo: 10 executions per day (patched)
        sid = (await make_suite(c, n=4))["id"]
        fake.usage[DEMO_USER.id] = 7                                      # 7 used, 3 left, run needs 4
        res = await c.post(f"/api/suites/{sid}/runs", json=run_body())
        assert res.status_code == 429 and "needs 4" in res.json()["detail"] and "3" in res.json()["detail"]

        fake.usage[DEMO_USER.id] = 6                                      # exactly enough
        run = (await c.post(f"/api/suites/{sid}/runs", json=run_body())).json()
        fake.usage[DEMO_USER.id] = 10                                     # used up elsewhere mid-run
        res = await c.post(f"/api/suite-runs/{run['id']}/cases/{run['cases'][0]['id']}/run")
        assert res.status_code == 429


@pytest.mark.asyncio
async def test_run_history_summary_counts_and_pruning(client, fake):
    async with client as c:
        sid = (await make_suite(c, n=1))["id"]
        with patch.object(suites_routes.settings, "max_suite_runs_per_suite", 2):
            ids = []
            for _ in range(3):
                run = (await c.post(f"/api/suites/{sid}/runs", json=run_body())).json()
                ids.append(run["id"])
                await c.post(f"/api/suite-runs/{run['id']}/cases/{run['cases'][0]['id']}/run")
        listed = (await c.get(f"/api/suites/{sid}/runs")).json()["runs"]
        assert [r["id"] for r in listed] == ids[:0:-1]                    # newest first; oldest pruned
        assert listed[0]["passed"] == 1 and listed[0]["status"] == "complete"
        assert ids[0] not in fake.runs and ids[0] not in fake.results


@pytest.mark.asyncio
async def test_runs_are_user_scoped(client, as_user):
    async with client as c:
        sid = (await make_suite(c, n=1))["id"]
        run = (await c.post(f"/api/suites/{sid}/runs", json=run_body())).json()
        as_user(DEMO_USER)
        for method, path in [("get", f"/api/suite-runs/{run['id']}"), ("post", f"/api/suite-runs/{run['id']}/cancel"),
                             ("post", f"/api/suite-runs/{run['id']}/cases/{run['cases'][0]['id']}/run"),
                             ("get", f"/api/suites/{sid}/runs")]:
            res = await getattr(c, method)(path)
            assert res.status_code == 404 or res.json().get("runs") == [], (method, path)


@pytest.mark.asyncio
async def test_snapshot_means_editing_the_suite_mid_run_changes_nothing(client):
    async with client as c:
        created = await make_suite(c, n=2)
        run = (await c.post(f"/api/suites/{created['id']}/runs", json=run_body())).json()
        await c.put(f"/api/suites/{created['id']}", json={"name": "x", "cases": []})
        res = await c.post(f"/api/suite-runs/{run['id']}/cases/{run['cases'][0]['id']}/run")
        assert res.status_code == 200 and res.json()["status"] == "passed"


@pytest.mark.asyncio
async def test_branching_workflow_produces_coverage_through_the_api(client):
    async with client as c:
        body = {"name": "s", "workflow_id": "wf-1", "cases": [
            {"name": f"c{i}", "assertions": [{"type": "max_steps", "max_steps": 6}]} for i in range(10)]}
        sid = (await c.post("/api/suites", json=body)).json()["id"]
        run = (await c.post(f"/api/suites/{sid}/runs", json=run_body(routed_workflow(), seed=0))).json()
        for ref in run["cases"]:
            assert (await c.post(f"/api/suite-runs/{run['id']}/cases/{ref['id']}/run")).status_code == 200
        report = (await c.get(f"/api/suite-runs/{run['id']}")).json()["report"]
        assert report["pass_rate"] == 1.0
        taken = report["coverage"]["edges_taken"]
        assert "c→p" in taken and "c→b" in taken                           # seeded schema output reaches both branches
        assert report["coverage"]["edges_never_taken"] == []


@pytest.mark.asyncio
async def test_suite_endpoints_require_auth(fake):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as c:
        for method, path in [("get", "/api/suites"), ("post", "/api/suites"), ("get", f"/api/suites/{uuid.uuid4()}"),
                             ("post", f"/api/suite-runs/{uuid.uuid4()}/cancel")]:
            res = await getattr(c, method)(path)
            assert res.status_code in (401, 403), (method, path)
