"""Test suites: definitions, runs (jobs) and the client-driven case executor (Task 50).

Design: docs/AiFlow - Async Suite Runs Design.md. The server owns the job and the budget; the
browser drives execution one case per request (each far below the 30 s gateway limit), so no
background worker is needed. Every query is scoped to the signed-in user.
"""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import ApprovedUser
from app.core import supabase_client as db
from app.core.config import settings
from app.models.user import UserProfile
from app.models.workflow import Workflow
from app.schemas.suites import (
    MAX_SUITE_BYTES,
    CaseRef,
    CaseResult,
    CreateSuiteRunRequest,
    SuiteCase,
    SuiteDetail,
    SuiteList,
    SuiteRunDetail,
    SuiteRunList,
    SuiteRunSummary,
    SuiteSummary,
    SuiteWrite,
)
from app.services.simulator import SimulationError, validate_for_simulation
from app.services.suite_runner import build_report, run_case

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _uuid(value: str, what: str = "Not found.") -> str:
    """Validate ids before they reach a PostgREST filter."""
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(status_code=404, detail=what)


def _max_cases(user: UserProfile) -> int:
    return settings.demo_max_cases_per_suite if user.role == "demo" else settings.approved_max_cases_per_suite


def _normalise_cases(body: SuiteWrite, user: UserProfile) -> list[dict[str, Any]]:
    """Check tier caps and size, assign ids, and return plain dicts ready to store."""
    cap = _max_cases(user)
    if len(body.cases) > cap:
        raise HTTPException(
            status_code=422,
            detail=f"A suite can have at most {cap} test cases on your plan (this one has {len(body.cases)}).",
        )
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case in body.cases:
        data = case.model_dump(exclude_unset=False, exclude_none=False)
        data["assertions"] = [a.model_dump(exclude_unset=True) for a in case.assertions]
        case_id = case.id or str(uuid.uuid4())
        if case_id in seen:
            raise HTTPException(status_code=422, detail=f"Duplicate test case id '{case_id}'.")
        seen.add(case_id)
        data["id"] = case_id
        cases.append(data)
    if len(json.dumps(cases, default=str)) > MAX_SUITE_BYTES:
        raise HTTPException(status_code=413, detail=f"The suite is too large (max {MAX_SUITE_BYTES // 1000} KB).")
    return cases


def _suite_detail(row: dict[str, Any]) -> SuiteDetail:
    return SuiteDetail(
        id=row["id"], workflow_id=row["workflow_id"], name=row["name"],
        cases=[SuiteCase(**c) for c in row.get("cases") or []],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


async def _owned_suite(user: UserProfile, suite_id: str) -> dict[str, Any]:
    row = await db.get_suite(user.id, _uuid(suite_id, "Suite not found."))
    if row is None:
        raise HTTPException(status_code=404, detail="Suite not found.")
    return row


async def _owned_run(user: UserProfile, run_id: str) -> dict[str, Any]:
    row = await db.get_suite_run(user.id, _uuid(run_id, "Suite run not found."))
    if row is None:
        raise HTTPException(status_code=404, detail="Suite run not found.")
    return row


def _daily_limit(user: UserProfile) -> int:
    return settings.demo_max_executions_per_day if user.role == "demo" else settings.approved_max_executions_per_day


async def _check_execution_budget(user: UserProfile, needed: int) -> None:
    """429 unless the user has ``needed`` executions left today (0 = unlimited)."""
    limit = _daily_limit(user)
    if limit <= 0:
        return
    used = (await db.get_usage_today(user.id)).get("executions", 0)
    if used + needed > limit:
        raise HTTPException(
            status_code=429,
            detail=f"This run needs {needed} execution(s) but only {max(0, limit - used)} of your daily {limit} remain. Try again tomorrow or use fewer cases.",
        )


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _settle(user: UserProfile, run: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    """Move a running job to its final state when it is done or has stalled. Returns the (updated) run row."""
    if run["status"] != "running":
        return run
    now = datetime.now(timezone.utc)
    patch: Optional[dict[str, Any]] = None
    if len(results) >= run["case_count"]:
        patch = {"status": "complete", "finished_at": now.isoformat()}
    elif now - _parse_time(run["created_at"]) > timedelta(minutes=settings.suite_job_stale_minutes):
        patch = {
            "status": "failed", "finished_at": now.isoformat(),
            "note": f"Stopped: not all cases finished within {settings.suite_job_stale_minutes} minutes.",
        }
    if patch is None:
        return run
    try:
        await db.update_suite_run(user.id, run["id"], patch)
    except Exception as exc:
        logger.warning("Could not settle suite run %s: %s", run["id"], exc)
    return {**run, **patch}


def _run_detail(run: dict[str, Any], result_rows: list[dict[str, Any]]) -> SuiteRunDetail:
    results = [CaseResult(**r["result"]) for r in result_rows]
    order = {c["id"]: i for i, c in enumerate(run["cases"])}
    results.sort(key=lambda r: order.get(r.case_id, 10**6))
    return SuiteRunDetail(
        id=run["id"], suite_id=run["suite_id"], status=run["status"], case_count=run["case_count"], seed=run["seed"],
        cases=[CaseRef(id=c["id"], name=c["name"]) for c in run["cases"]],
        results=results,
        report=build_report(run["workflow"], run["case_count"], [r.model_dump() for r in results]),
        created_at=run["created_at"], finished_at=run.get("finished_at"), note=run.get("note"),
    )


# ── Suite definitions ────────────────────────────────────────────────────────

@router.get("/suites", response_model=SuiteList)
async def list_suites(user: ApprovedUser, workflow_id: Optional[str] = Query(default=None, max_length=100)):
    rows = await db.list_suites(user.id, workflow_id)
    return SuiteList(suites=[
        SuiteSummary(id=r["id"], workflow_id=r["workflow_id"], name=r["name"],
                     case_count=r.get("case_count", 0), updated_at=r["updated_at"])
        for r in rows
    ])


@router.post("/suites", response_model=SuiteDetail, status_code=status.HTTP_201_CREATED)
async def create_suite(body: SuiteWrite, user: ApprovedUser):
    if not body.workflow_id:
        raise HTTPException(status_code=422, detail="workflow_id is required.")
    if await db.count_suites(user.id) >= settings.max_suites_per_user:
        raise HTTPException(status_code=409, detail=f"You can have at most {settings.max_suites_per_user} suites. Delete one first.")
    cases = _normalise_cases(body, user)
    row = await db.insert_suite({
        "user_id": user.id, "workflow_id": body.workflow_id, "name": body.name,
        "cases": cases, "case_count": len(cases),
    })
    return _suite_detail(row)


@router.get("/suites/{suite_id}", response_model=SuiteDetail)
async def get_suite(suite_id: str, user: ApprovedUser):
    return _suite_detail(await _owned_suite(user, suite_id))


@router.put("/suites/{suite_id}", response_model=SuiteDetail)
async def update_suite(suite_id: str, body: SuiteWrite, user: ApprovedUser):
    await _owned_suite(user, suite_id)
    cases = _normalise_cases(body, user)
    row = await db.update_suite(user.id, suite_id, {"name": body.name, "cases": cases, "case_count": len(cases)})
    if row is None:
        raise HTTPException(status_code=404, detail="Suite not found.")
    return _suite_detail(row)


@router.delete("/suites/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_suite(suite_id: str, user: ApprovedUser):
    if not await db.delete_suite(user.id, _uuid(suite_id, "Suite not found.")):
        raise HTTPException(status_code=404, detail="Suite not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Runs ─────────────────────────────────────────────────────────────────────

@router.post("/suites/{suite_id}/runs", response_model=SuiteRunDetail, status_code=status.HTTP_201_CREATED)
async def create_suite_run(suite_id: str, body: CreateSuiteRunRequest, user: ApprovedUser):
    suite = await _owned_suite(user, suite_id)
    cases = suite.get("cases") or []
    if not cases:
        raise HTTPException(status_code=422, detail="This suite has no test cases yet.")
    if len(cases) > _max_cases(user):
        raise HTTPException(status_code=422, detail=f"This suite has more cases than your plan allows ({_max_cases(user)}).")
    if body.workflow.id != suite["workflow_id"]:
        raise HTTPException(status_code=422, detail="This suite belongs to a different workflow.")
    try:
        validate_for_simulation(body.workflow)
    except SimulationError as exc:
        raise HTTPException(status_code=422, detail=f"The workflow cannot be simulated: {exc}")
    await _check_execution_budget(user, len(cases))

    row = await db.insert_suite_run({
        "user_id": user.id, "suite_id": suite["id"], "case_count": len(cases), "seed": body.seed,
        "workflow": body.workflow.model_dump(mode="json"), "cases": cases,
    })
    try:
        await db.prune_suite_runs(user.id, suite["id"], settings.max_suite_runs_per_suite)
    except Exception as exc:
        logger.warning("Suite run pruning failed: %s", exc)
    return _run_detail(row, [])


@router.get("/suites/{suite_id}/runs", response_model=SuiteRunList)
async def list_suite_runs(suite_id: str, user: ApprovedUser, limit: int = Query(10, ge=1, le=50)):
    rows = await db.list_suite_runs(user.id, _uuid(suite_id, "Suite not found."), limit)
    runs = []
    for r in rows:
        statuses = [x["status"] for x in r.get("suite_case_results") or []]
        runs.append(SuiteRunSummary(
            id=r["id"], suite_id=r["suite_id"], status=r["status"], case_count=r["case_count"],
            passed=statuses.count("passed"), failed=statuses.count("failed"), errors=statuses.count("error"),
            created_at=r["created_at"], finished_at=r.get("finished_at"),
        ))
    return SuiteRunList(runs=runs)


@router.get("/suite-runs/{run_id}", response_model=SuiteRunDetail)
async def get_suite_run(run_id: str, user: ApprovedUser):
    run = await _owned_run(user, run_id)
    results = await db.list_case_results(user.id, run["id"])
    run = await _settle(user, run, results)
    return _run_detail(run, results)


@router.post("/suite-runs/{run_id}/cancel", response_model=SuiteRunDetail)
async def cancel_suite_run(run_id: str, user: ApprovedUser):
    run = await _owned_run(user, run_id)
    if run["status"] == "running":
        patch = {"status": "cancelled", "finished_at": datetime.now(timezone.utc).isoformat()}
        await db.update_suite_run(user.id, run["id"], patch)
        run = {**run, **patch}
    return _run_detail(run, await db.list_case_results(user.id, run["id"]))


@router.post("/suite-runs/{run_id}/cases/{case_id}/run", response_model=CaseResult)
async def run_suite_case(run_id: str, case_id: str, user: ApprovedUser):
    run = await _owned_run(user, run_id)
    index = next((i for i, c in enumerate(run["cases"]) if c["id"] == case_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Test case not found in this run.")

    existing = await db.get_case_result(user.id, run["id"], case_id)
    if existing is not None:                      # idempotent: repeating a case returns the stored result
        return CaseResult(**existing["result"])
    if run["status"] != "running":
        raise HTTPException(status_code=409, detail=f"This run is {run['status']}; no more cases can be executed.")

    await _check_execution_budget(user, 1)
    result = await run_case(Workflow.model_validate(run["workflow"]), run["cases"][index], index, run["seed"])

    inserted = await db.insert_case_result({
        "run_id": run["id"], "case_id": case_id, "user_id": user.id,
        "status": result.status, "result": result.model_dump(mode="json"),
    })
    if inserted:                                  # only the request that stored the result is charged
        await db.increment_usage(user.id, "executions")
        results = await db.list_case_results(user.id, run["id"])
        await _settle(user, run, results)
    else:                                         # lost a race with an identical request
        stored = await db.get_case_result(user.id, run["id"], case_id)
        if stored is not None:
            return CaseResult(**stored["result"])
    return result
