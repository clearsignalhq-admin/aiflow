"""List, fetch and delete the current user's persisted simulation runs (Task 42)."""
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel

from app.api.deps import ApprovedUser
from app.core import supabase_client as db
from app.schemas.simulation import ExecutionTrace, SimulationEvaluation, SimulationSettings
from app.models.workflow import Workflow

router = APIRouter(prefix="/api")


class RunSummary(BaseModel):
    id: str
    workflow_id: str
    workflow_name: str
    status: str
    step_count: int
    truncated: bool = False
    evaluation_score: Optional[int] = None
    created_at: str


class RunListResponse(BaseModel):
    runs: list[RunSummary]


class RunDetail(BaseModel):
    id: str
    workflow_id: str
    workflow_name: str
    status: str
    step_count: int
    truncated: bool = False
    created_at: str
    settings: SimulationSettings
    input: dict[str, Any]
    workflow: Workflow
    trace: ExecutionTrace
    evaluation: Optional[SimulationEvaluation] = None


def _parse_run_id(run_id: str) -> str:
    try:
        return str(uuid.UUID(run_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Run not found.")


def _score(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    user: ApprovedUser,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
):
    rows = await db.list_runs(user.id, limit, offset)
    return RunListResponse(runs=[
        RunSummary(**{**r, "evaluation_score": _score(r.get("evaluation_score"))}) for r in rows
    ])


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, user: ApprovedUser):
    row = await db.get_run(user.id, _parse_run_id(run_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return RunDetail(**row)


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: str, user: ApprovedUser):
    if not await db.delete_run(user.id, _parse_run_id(run_id)):
        raise HTTPException(status_code=404, detail="Run not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
