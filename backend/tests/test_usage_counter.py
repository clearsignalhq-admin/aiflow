"""Tests for the atomic usage counter (Task 47). The SQL itself runs in Supabase; here we pin the contract."""
import asyncio
import json
import re
from datetime import date
from pathlib import Path

import httpx
import pytest
from unittest.mock import patch

from app.core import supabase_client as sc

SUPABASE_DIR = Path(__file__).resolve().parents[2] / "supabase"


def _factory(handler):
    original = httpx.AsyncClient
    return lambda *a, **k: original(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_increment_calls_the_rpc_once_with_explicit_date_and_amount():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(204)

    with patch.object(sc.httpx, "AsyncClient", _factory(handler)):
        await sc.increment_usage("u1", "executions")
        await sc.increment_usage("u1", "llm_requests", by=5)

    assert len(seen) == 2                                       # one request each: no read-then-write
    method, path, body = seen[0]
    assert (method, path) == ("POST", "/rest/v1/rpc/increment_usage")
    assert body == {"p_user_id": "u1", "p_field": "executions", "p_by": 1, "p_date": date.today().isoformat()}
    assert seen[1][2]["p_by"] == 5 and seen[1][2]["p_field"] == "llm_requests"


@pytest.mark.asyncio
async def test_concurrent_increments_are_all_sent_independently():
    """The old implementation read the counter first; 20 parallel calls must now be 20 independent RPCs."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["p_by"])
        return httpx.Response(204)

    with patch.object(sc.httpx, "AsyncClient", _factory(handler)):
        await asyncio.gather(*[sc.increment_usage("u1", "executions") for _ in range(20)])
    assert sum(calls) == 20 and len(calls) == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("field,by", [("is_admin", 1), ("executions; drop table x", 1), ("", 1), ("executions", 0), ("executions", -3)])
async def test_invalid_input_is_rejected_before_any_request(field, by):
    def handler(request):  # pragma: no cover - must not be reached
        raise AssertionError("no request expected")

    with patch.object(sc.httpx, "AsyncClient", _factory(handler)):
        with pytest.raises(ValueError):
            await sc.increment_usage("u1", field, by)


@pytest.mark.asyncio
async def test_database_errors_propagate_to_the_caller():
    with patch.object(sc.httpx, "AsyncClient", _factory(lambda r: httpx.Response(500, json={"message": "boom"}))):
        with pytest.raises(httpx.HTTPStatusError):
            await sc.increment_usage("u1", "executions")


# ── The migration and schema.sql must agree and stay locked down ─────────────

def _sql(name):
    return (SUPABASE_DIR / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def test_function_is_in_both_the_migration_and_schema():
    migration = _sql("update_202611241500.sql")
    schema = _sql("schema.sql")
    assert "create or replace function public.increment_usage(" in migration
    body = migration[migration.index("create or replace function"):]
    assert body.strip() in schema                              # schema.sql contains the exact delta


def test_function_is_service_role_only_and_security_definer():
    sql = _sql("update_202611241500.sql")
    assert "security definer" in sql and "set search_path = public" in sql
    assert re.search(r"revoke all on function public\.increment_usage\(uuid, text, integer, date\)\s+from public, anon, authenticated", sql)
    assert re.search(r"grant execute on function public\.increment_usage\(uuid, text, integer, date\)\s+to service_role", sql)


def test_function_whitelists_fields_and_adds_atomically():
    sql = _sql("update_202611241500.sql")
    assert "p_field = 'executions'" in sql and "p_field = 'llm_requests'" in sql and "raise exception 'unknown usage field" in sql
    assert "usage_tracking.executions + excluded.executions" in sql
    assert "usage_tracking.llm_requests + excluded.llm_requests" in sql
    assert "p_by < 1" in sql


def test_every_migration_since_task_42_is_reflected_in_schema():
    schema = _sql("schema.sql")
    assert "continuation  jsonb" in schema                      # Task 46
    assert "create table if not exists public.workflow_runs" in schema   # Task 42
