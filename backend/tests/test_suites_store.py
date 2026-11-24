"""PostgREST requests made by the suites store (Task 50): always user-scoped, results idempotent."""
import json
from unittest.mock import patch

import httpx
import pytest

from app.core import supabase_client as sc


def _factory(handler):
    original = httpx.AsyncClient
    return lambda *a, **k: original(transport=httpx.MockTransport(handler))


class Recorder:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append({
            "method": request.method, "path": request.url.path, "params": dict(request.url.params),
            "prefer": request.headers.get("prefer"), "json": json.loads(request.content) if request.content else None,
        })
        return httpx.Response(200, json=self.body)


@pytest.mark.asyncio
async def test_every_suite_query_is_scoped_to_the_user():
    rec = Recorder([{"id": "x", "status": "running"}])
    with patch.object(sc.httpx, "AsyncClient", _factory(rec)):
        await sc.list_suites("u1", "wf")
        await sc.count_suites("u1")
        await sc.get_suite("u1", "s1")
        await sc.update_suite("u1", "s1", {"name": "n"})
        await sc.delete_suite("u1", "s1")
        await sc.get_suite_run("u1", "r1")
        await sc.update_suite_run("u1", "r1", {"status": "cancelled"})
        await sc.list_suite_runs("u1", "s1", 5)
        await sc.list_case_results("u1", "r1")
        await sc.get_case_result("u1", "r1", "c1")
    assert len(rec.calls) == 10
    assert all(c["params"]["user_id"] == "eq.u1" for c in rec.calls)
    assert rec.calls[0]["params"]["workflow_id"] == "eq.wf" and "cases" not in rec.calls[0]["params"]["select"]


@pytest.mark.asyncio
async def test_inserts_carry_the_owner_and_return_the_row():
    rec = Recorder([{"id": "new"}])
    with patch.object(sc.httpx, "AsyncClient", _factory(rec)):
        assert await sc.insert_suite({"user_id": "u1", "name": "n"}) == {"id": "new"}
        assert await sc.insert_suite_run({"user_id": "u1"}) == {"id": "new"}
    assert all(c["method"] == "POST" and c["json"]["user_id"] == "u1" for c in rec.calls)


@pytest.mark.asyncio
async def test_case_result_insert_is_idempotent_and_reports_whether_it_stored_anything():
    rec = Recorder([{"case_id": "c1"}])
    with patch.object(sc.httpx, "AsyncClient", _factory(rec)):
        assert await sc.insert_case_result({"run_id": "r", "case_id": "c1", "user_id": "u1"}) is True
    call = rec.calls[0]
    assert "ignore-duplicates" in call["prefer"] and "return=representation" in call["prefer"]
    assert call["params"]["on_conflict"] == "run_id,case_id"

    with patch.object(sc.httpx, "AsyncClient", _factory(Recorder([]))):      # duplicate: PostgREST returns no row
        assert await sc.insert_case_result({"run_id": "r", "case_id": "c1", "user_id": "u1"}) is False


@pytest.mark.asyncio
async def test_missing_rows_come_back_as_none_or_false():
    with patch.object(sc.httpx, "AsyncClient", _factory(Recorder([]))):
        assert await sc.get_suite("u1", "s") is None
        assert await sc.get_suite_run("u1", "r") is None
        assert await sc.get_case_result("u1", "r", "c") is None
        assert await sc.update_suite("u1", "s", {}) is None
        assert await sc.delete_suite("u1", "s") is False
        assert await sc.update_suite_run("u1", "r", {}) is False


@pytest.mark.asyncio
async def test_prune_keeps_the_newest_runs_and_deletes_only_the_users_stale_ones():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, dict(request.url.params)))
        return httpx.Response(200, json=[{"id": "old1"}, {"id": "old2"}] if request.method == "GET" else [])

    with patch.object(sc.httpx, "AsyncClient", _factory(handler)):
        await sc.prune_suite_runs("u1", "s1", 20)
    assert [m for m, _ in seen] == ["GET", "DELETE"]
    assert seen[0][1]["offset"] == "20" and seen[0][1]["order"] == "created_at.desc" and seen[0][1]["suite_id"] == "eq.s1"
    assert seen[1][1]["id"] == "in.(old1,old2)" and seen[1][1]["user_id"] == "eq.u1"


@pytest.mark.asyncio
async def test_database_errors_propagate():
    with patch.object(sc.httpx, "AsyncClient", _factory(lambda r: httpx.Response(500, json={"message": "boom"}))):
        with pytest.raises(httpx.HTTPStatusError):
            await sc.get_suite("u1", "s")


# ── Migration and schema.sql agree ───────────────────────────────────────────

def test_migration_is_contained_in_schema_and_locked_down():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "supabase"
    mig = (root / "update_202611241600.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    schema = (root / "schema.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    for table in ("suites", "suite_runs", "suite_case_results"):
        assert f"create table if not exists public.{table}" in mig and f"create table if not exists public.{table}" in schema
        assert f"alter table public.{table}" in mig and "enable row level security" in mig
    for fragment in ("primary key (run_id, case_id)", "case_count  integer", "check (status in ('running', 'complete', 'cancelled', 'failed'))"):
        assert fragment in mig and fragment in schema
    # users may only read; no insert/update/delete policy exists for them
    assert mig.count("create policy") == 3 and all("for select" in p for p in mig.split("create policy")[1:])
