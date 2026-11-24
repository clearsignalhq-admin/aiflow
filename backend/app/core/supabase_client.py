"""
Thin async wrapper around the Supabase REST API using httpx.
Uses the service role key — never expose this to the frontend.
"""
import logging
import time
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Simple in-process cache: {user_id: (profile_dict, expires_at)}
_profile_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 60  # seconds


def _base_headers() -> dict[str, str]:
    return {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def get_user_profile(user_id: str) -> Optional[dict[str, Any]]:
    cached = _profile_cache.get(user_id)
    if cached and cached[1] > time.time():
        return cached[0]

    url = f"{settings.supabase_url}/rest/v1/user_profiles"
    params = {"id": f"eq.{user_id}", "select": "*", "limit": "1"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_base_headers(), params=params)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return None
        profile = rows[0]
        _profile_cache[user_id] = (profile, time.time() + _CACHE_TTL)
        return profile


def invalidate_profile_cache(user_id: str) -> None:
    _profile_cache.pop(user_id, None)


async def update_user_profile(user_id: str, patch: dict[str, Any]) -> None:
    url = f"{settings.supabase_url}/rest/v1/user_profiles"
    params = {"id": f"eq.{user_id}"}
    async with httpx.AsyncClient() as client:
        resp = await client.patch(url, headers=_base_headers(), params=params, json=patch)
        resp.raise_for_status()
    invalidate_profile_cache(user_id)


async def get_all_users() -> list[dict[str, Any]]:
    url = f"{settings.supabase_url}/rest/v1/user_profiles"
    params = {"select": "*", "order": "created_at.desc"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_base_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def get_access_requests(status: Optional[str] = None) -> list[dict[str, Any]]:
    url = f"{settings.supabase_url}/rest/v1/access_requests"
    params: dict[str, str] = {"select": "*", "order": "created_at.desc"}
    if status:
        params["status"] = f"eq.{status}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_base_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def insert_access_request(data: dict[str, Any]) -> dict[str, Any]:
    url = f"{settings.supabase_url}/rest/v1/access_requests"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=_base_headers(), json=data)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else {}


async def update_access_request(request_id: str, patch: dict[str, Any]) -> None:
    url = f"{settings.supabase_url}/rest/v1/access_requests"
    params = {"id": f"eq.{request_id}"}
    async with httpx.AsyncClient() as client:
        resp = await client.patch(url, headers=_base_headers(), params=params, json=patch)
        resp.raise_for_status()


async def get_usage_today(user_id: str) -> dict[str, Any]:
    from datetime import date
    today = date.today().isoformat()
    url = f"{settings.supabase_url}/rest/v1/usage_tracking"
    params = {
        "user_id": f"eq.{user_id}",
        "date": f"eq.{today}",
        "select": "*",
        "limit": "1",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_base_headers(), params=params)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else {"user_id": user_id, "date": today, "executions": 0, "llm_requests": 0}


async def insert_analytics_event(
    event: str, page: Optional[str] = None, user_id: Optional[str] = None
) -> None:
    url = f"{settings.supabase_url}/rest/v1/analytics_events"
    headers = {**_base_headers(), "Prefer": "return=minimal"}
    payload: dict[str, Any] = {"event": event}
    if page:
        payload["page"] = page
    if user_id:
        payload["user_id"] = user_id
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("Analytics event '%s' not recorded: %s", event, exc)  # non-fatal


async def get_analytics_summary() -> dict[str, Any]:
    from datetime import date, timedelta
    since = (date.today() - timedelta(days=30)).isoformat()
    url = f"{settings.supabase_url}/rest/v1/analytics_events"
    params = {
        "select": "event,page,created_at",
        "created_at": f"gte.{since}T00:00:00Z",
        "order": "created_at.desc",
        "limit": "5000",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_base_headers(), params=params)
        resp.raise_for_status()
        events = resp.json()

    totals: dict[str, int] = {}
    by_date: dict[str, dict[str, int]] = {}
    for e in events:
        etype = e["event"]
        totals[etype] = totals.get(etype, 0) + 1
        day = e["created_at"][:10]
        by_date.setdefault(day, {})
        by_date[day][etype] = by_date[day].get(etype, 0) + 1

    daily = [
        {"date": day, "event": evt, "count": cnt}
        for day, evts in sorted(by_date.items())
        for evt, cnt in evts.items()
    ]
    return {"totals": totals, "daily": daily}


async def bootstrap_admin(email: str) -> None:
    """On startup: promote the given email to approved admin if they exist and aren't already."""
    url = f"{settings.supabase_url}/rest/v1/user_profiles"
    params = {"email": f"eq.{email}", "select": "id,access_status,role", "limit": "1"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_base_headers(), params=params)
        resp.raise_for_status()
        rows = resp.json()
    if not rows:
        return  # user hasn't signed up yet — nothing to do
    profile = rows[0]
    if profile["access_status"] == "approved" and profile["role"] == "admin":
        return  # already correct
    patch_params = {"id": f"eq.{profile['id']}"}
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            url,
            headers=_base_headers(),
            params=patch_params,
            json={"access_status": "approved", "role": "admin"},
        )
        resp.raise_for_status()
    invalidate_profile_cache(profile["id"])
    logger.info("bootstrap: promoted %s to approved admin", email)


USAGE_FIELDS = ("executions", "llm_requests")


async def increment_usage(user_id: str, field: str, by: int = 1) -> None:
    """Atomically add ``by`` to today's counter via the ``increment_usage`` SQL function.

    A single statement does the insert-or-add, so concurrent requests (and suite runs that add
    many units at once) are all counted. The date is sent explicitly so reads (get_usage_today)
    and writes always agree on which day a request belongs to.
    """
    from datetime import date
    if field not in USAGE_FIELDS:
        raise ValueError(f"Unknown usage field: {field!r}")
    if by < 1:
        raise ValueError("by must be a positive integer")
    url = f"{settings.supabase_url}/rest/v1/rpc/increment_usage"
    headers = {**_base_headers(), "Prefer": "return=minimal"}
    payload = {"p_user_id": user_id, "p_field": field, "p_by": by, "p_date": date.today().isoformat()}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()


# ── Workflow runs (Task 42) ──────────────────────────────────────────────────
# Every query is scoped by user_id; callers pass the authenticated user's id.

_RUN_SUMMARY_COLUMNS = (
    "id,workflow_id,workflow_name,status,step_count,truncated,created_at,"
    "evaluation_score:evaluation->>score"
)


async def insert_run(record: dict[str, Any]) -> None:
    url = f"{settings.supabase_url}/rest/v1/workflow_runs"
    headers = {**_base_headers(), "Prefer": "return=minimal"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=record)
        resp.raise_for_status()


async def update_run(user_id: str, run_id: str, patch: dict[str, Any]) -> bool:
    url = f"{settings.supabase_url}/rest/v1/workflow_runs"
    params = {"id": f"eq.{run_id}", "user_id": f"eq.{user_id}"}
    async with httpx.AsyncClient() as client:
        resp = await client.patch(url, headers=_base_headers(), params=params, json=patch)
        resp.raise_for_status()
        return bool(resp.json())


async def list_runs(user_id: str, limit: int, offset: int) -> list[dict[str, Any]]:
    url = f"{settings.supabase_url}/rest/v1/workflow_runs"
    params = {
        "user_id": f"eq.{user_id}",
        "select": _RUN_SUMMARY_COLUMNS,
        "order": "created_at.desc",
        "limit": str(limit),
        "offset": str(offset),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_base_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def get_run(user_id: str, run_id: str) -> Optional[dict[str, Any]]:
    url = f"{settings.supabase_url}/rest/v1/workflow_runs"
    params = {"id": f"eq.{run_id}", "user_id": f"eq.{user_id}", "select": "*", "limit": "1"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_base_headers(), params=params)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None


async def delete_run(user_id: str, run_id: str) -> bool:
    url = f"{settings.supabase_url}/rest/v1/workflow_runs"
    params = {"id": f"eq.{run_id}", "user_id": f"eq.{user_id}"}
    async with httpx.AsyncClient() as client:
        resp = await client.delete(url, headers=_base_headers(), params=params)
        resp.raise_for_status()
        return bool(resp.json())


async def prune_runs(user_id: str, keep: int, older_than_iso: Optional[str]) -> None:
    """Delete a user's runs older than ``older_than_iso`` and any beyond the newest ``keep``."""
    url = f"{settings.supabase_url}/rest/v1/workflow_runs"
    headers = {**_base_headers(), "Prefer": "return=minimal"}
    async with httpx.AsyncClient() as client:
        if older_than_iso:
            resp = await client.delete(
                url, headers=headers,
                params={"user_id": f"eq.{user_id}", "created_at": f"lt.{older_than_iso}"},
            )
            resp.raise_for_status()
        if keep > 0:
            resp = await client.get(
                url, headers=_base_headers(),
                params={"user_id": f"eq.{user_id}", "select": "id", "order": "created_at.desc",
                        "offset": str(keep), "limit": "1000"},
            )
            resp.raise_for_status()
            stale = [r["id"] for r in resp.json()]
            if stale:
                resp = await client.delete(
                    url, headers=headers,
                    params={"user_id": f"eq.{user_id}", "id": f"in.({','.join(stale)})"},
                )
                resp.raise_for_status()


# ── Test suites (Task 50) ────────────────────────────────────────────────────
# Every query is scoped by user_id; callers pass the authenticated user's id.

async def list_suites(user_id: str, workflow_id: Optional[str]) -> list[dict[str, Any]]:
    params = {
        "user_id": f"eq.{user_id}",
        "select": "id,workflow_id,name,case_count,updated_at",
        "order": "updated_at.desc",
        "limit": "100",
    }
    if workflow_id:
        params["workflow_id"] = f"eq.{workflow_id}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.supabase_url}/rest/v1/suites", headers=_base_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def count_suites(user_id: str) -> int:
    params = {"user_id": f"eq.{user_id}", "select": "id", "limit": "1000"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.supabase_url}/rest/v1/suites", headers=_base_headers(), params=params)
        resp.raise_for_status()
        return len(resp.json())


async def get_suite(user_id: str, suite_id: str) -> Optional[dict[str, Any]]:
    params = {"id": f"eq.{suite_id}", "user_id": f"eq.{user_id}", "select": "*", "limit": "1"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.supabase_url}/rest/v1/suites", headers=_base_headers(), params=params)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None


async def insert_suite(record: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{settings.supabase_url}/rest/v1/suites", headers=_base_headers(), json=record)
        resp.raise_for_status()
        return resp.json()[0]


async def update_suite(user_id: str, suite_id: str, patch: dict[str, Any]) -> Optional[dict[str, Any]]:
    params = {"id": f"eq.{suite_id}", "user_id": f"eq.{user_id}"}
    async with httpx.AsyncClient() as client:
        resp = await client.patch(f"{settings.supabase_url}/rest/v1/suites", headers=_base_headers(), params=params, json=patch)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None


async def delete_suite(user_id: str, suite_id: str) -> bool:
    params = {"id": f"eq.{suite_id}", "user_id": f"eq.{user_id}"}
    async with httpx.AsyncClient() as client:
        resp = await client.delete(f"{settings.supabase_url}/rest/v1/suites", headers=_base_headers(), params=params)
        resp.raise_for_status()
        return bool(resp.json())


async def insert_suite_run(record: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{settings.supabase_url}/rest/v1/suite_runs", headers=_base_headers(), json=record)
        resp.raise_for_status()
        return resp.json()[0]


async def get_suite_run(user_id: str, run_id: str) -> Optional[dict[str, Any]]:
    params = {"id": f"eq.{run_id}", "user_id": f"eq.{user_id}", "select": "*", "limit": "1"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.supabase_url}/rest/v1/suite_runs", headers=_base_headers(), params=params)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None


async def update_suite_run(user_id: str, run_id: str, patch: dict[str, Any]) -> bool:
    params = {"id": f"eq.{run_id}", "user_id": f"eq.{user_id}"}
    async with httpx.AsyncClient() as client:
        resp = await client.patch(f"{settings.supabase_url}/rest/v1/suite_runs", headers=_base_headers(), params=params, json=patch)
        resp.raise_for_status()
        return bool(resp.json())


async def list_suite_runs(user_id: str, suite_id: str, limit: int) -> list[dict[str, Any]]:
    params = {
        "user_id": f"eq.{user_id}",
        "suite_id": f"eq.{suite_id}",
        "select": "id,suite_id,status,case_count,seed,created_at,finished_at,suite_case_results(status)",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.supabase_url}/rest/v1/suite_runs", headers=_base_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def prune_suite_runs(user_id: str, suite_id: str, keep: int) -> None:
    """Delete a suite's runs beyond the newest ``keep`` (their case results go with them)."""
    url = f"{settings.supabase_url}/rest/v1/suite_runs"
    headers = {**_base_headers(), "Prefer": "return=minimal"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_base_headers(), params={
            "user_id": f"eq.{user_id}", "suite_id": f"eq.{suite_id}", "select": "id",
            "order": "created_at.desc", "offset": str(keep), "limit": "1000"})
        resp.raise_for_status()
        stale = [r["id"] for r in resp.json()]
        if stale:
            resp = await client.delete(url, headers=headers, params={
                "user_id": f"eq.{user_id}", "id": f"in.({','.join(stale)})"})
            resp.raise_for_status()


async def list_case_results(user_id: str, run_id: str) -> list[dict[str, Any]]:
    params = {"user_id": f"eq.{user_id}", "run_id": f"eq.{run_id}", "select": "case_id,status,result", "limit": "1000"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.supabase_url}/rest/v1/suite_case_results", headers=_base_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def get_case_result(user_id: str, run_id: str, case_id: str) -> Optional[dict[str, Any]]:
    params = {"user_id": f"eq.{user_id}", "run_id": f"eq.{run_id}", "case_id": f"eq.{case_id}",
              "select": "case_id,status,result", "limit": "1"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.supabase_url}/rest/v1/suite_case_results", headers=_base_headers(), params=params)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None


async def insert_case_result(record: dict[str, Any]) -> bool:
    """Store a case result once. Returns False if one already existed (duplicate request)."""
    headers = {**_base_headers(), "Prefer": "resolution=ignore-duplicates,return=representation"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.supabase_url}/rest/v1/suite_case_results", headers=headers,
            params={"on_conflict": "run_id,case_id"}, json=record)
        resp.raise_for_status()
        return bool(resp.json())


# ── Cloud workflows (Task 61) ───────────────────────────────────────────────

_CLOUD = "cloud_workflows"
_VERSIONS = "workflow_versions"
_CLOUD_LIST_FIELDS = "id,name,version_count,share_token,updated_at,created_at"


async def list_cloud_workflows(user_id: str) -> list[dict[str, Any]]:
    params = {"user_id": f"eq.{user_id}", "select": _CLOUD_LIST_FIELDS, "order": "updated_at.desc", "limit": "200"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.supabase_url}/rest/v1/{_CLOUD}", headers=_base_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def count_cloud_workflows(user_id: str) -> int:
    return len(await list_cloud_workflows(user_id))


async def get_cloud_workflow(user_id: str, workflow_id: str) -> Optional[dict[str, Any]]:
    params = {"id": f"eq.{workflow_id}", "user_id": f"eq.{user_id}", "select": "*", "limit": "1"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.supabase_url}/rest/v1/{_CLOUD}", headers=_base_headers(), params=params)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None


async def get_cloud_workflow_by_token(token: str) -> Optional[dict[str, Any]]:
    """Public lookup for share links: only the fields a viewer may see."""
    params = {"share_token": f"eq.{token}", "select": "name,workflow,shared_at", "limit": "1"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.supabase_url}/rest/v1/{_CLOUD}", headers=_base_headers(), params=params)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None


async def insert_cloud_workflow(record: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{settings.supabase_url}/rest/v1/{_CLOUD}", headers=_base_headers(), json=record)
        resp.raise_for_status()
        return resp.json()[0]


async def update_cloud_workflow(user_id: str, workflow_id: str, patch: dict[str, Any]) -> Optional[dict[str, Any]]:
    params = {"id": f"eq.{workflow_id}", "user_id": f"eq.{user_id}"}
    async with httpx.AsyncClient() as client:
        resp = await client.patch(f"{settings.supabase_url}/rest/v1/{_CLOUD}", headers=_base_headers(), params=params, json=patch)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None


async def delete_cloud_workflow(user_id: str, workflow_id: str) -> bool:
    params = {"id": f"eq.{workflow_id}", "user_id": f"eq.{user_id}"}
    async with httpx.AsyncClient() as client:
        resp = await client.delete(f"{settings.supabase_url}/rest/v1/{_CLOUD}", headers=_base_headers(), params=params)
        resp.raise_for_status()
        return bool(resp.json())


async def insert_workflow_version(record: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{settings.supabase_url}/rest/v1/{_VERSIONS}", headers=_base_headers(), json=record)
        resp.raise_for_status()
        return resp.json()[0]


async def list_workflow_versions(user_id: str, workflow_id: str) -> list[dict[str, Any]]:
    params = {"user_id": f"eq.{user_id}", "workflow_id": f"eq.{workflow_id}", "select": "version,label,created_at,workflow",
              "order": "version.desc", "limit": "200"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.supabase_url}/rest/v1/{_VERSIONS}", headers=_base_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def get_workflow_version(user_id: str, workflow_id: str, version: int) -> Optional[dict[str, Any]]:
    params = {"user_id": f"eq.{user_id}", "workflow_id": f"eq.{workflow_id}", "version": f"eq.{version}", "select": "*", "limit": "1"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{settings.supabase_url}/rest/v1/{_VERSIONS}", headers=_base_headers(), params=params)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None


async def prune_workflow_versions(user_id: str, workflow_id: str, keep: int) -> None:
    """Delete a workflow's versions beyond the newest ``keep``."""
    url = f"{settings.supabase_url}/rest/v1/{_VERSIONS}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_base_headers(), params={
            "user_id": f"eq.{user_id}", "workflow_id": f"eq.{workflow_id}", "select": "id",
            "order": "version.desc", "offset": str(keep), "limit": "1000"})
        resp.raise_for_status()
        stale = [r["id"] for r in resp.json()]
        if stale:
            resp = await client.delete(url, headers={**_base_headers(), "Prefer": "return=minimal"}, params={
                "user_id": f"eq.{user_id}", "id": f"in.({','.join(stale)})"})
            resp.raise_for_status()
