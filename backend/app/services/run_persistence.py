"""Persist simulation runs (Task 42).

Persistence is best-effort: a Supabase outage or an oversized run must never fail the
simulation the user just ran. Every failure is logged, and callers get ``None``.

Caps:
  * ``max_run_bytes``     — a run record larger than this drops step inputs/outputs
                            (``truncated=True``); if it is still too large it is not stored.
  * ``max_runs_per_user`` — oldest runs beyond this are deleted after each insert.
  * ``run_retention_days``— runs older than this are deleted after each insert.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core import supabase_client as db
from app.core.config import settings
from app.models.workflow import Workflow
from app.schemas.simulation import ExecutionTrace, SimulationEvaluation, SimulationSettings
from app.services import simulator

logger = logging.getLogger(__name__)


def _size(record: dict[str, Any]) -> int:
    return len(json.dumps(record, default=str))


def build_run_record(
    user_id: str,
    workflow: Workflow,
    input_data: dict[str, Any],
    sim_settings: SimulationSettings,
    trace: ExecutionTrace,
    evaluation: Optional[SimulationEvaluation],
    max_bytes: Optional[int] = None,
    continuation: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Return the row to store, shrunk to the size cap, or None if it cannot be made to fit."""
    cap = settings.max_run_bytes if max_bytes is None else max_bytes
    record: dict[str, Any] = {
        "id": trace.trace_id,
        "user_id": user_id,
        "workflow_id": workflow.id,
        "workflow_name": workflow.name,
        "status": trace.status,
        "step_count": len(trace.steps),
        "settings": sim_settings.model_dump(mode="json"),
        "input": input_data,
        "workflow": workflow.model_dump(mode="json"),
        "trace": trace.model_dump(mode="json"),
        "evaluation": evaluation.model_dump(mode="json") if evaluation else None,
        "truncated": False,
        "continuation": continuation,
    }
    if _size(record) <= cap:
        return record

    for step in record["trace"]["steps"]:
        step["input"] = None
        step["output"] = None
    record["input"] = {}
    record["truncated"] = True
    return record if _size(record) <= cap else None


def build_run_update(trace: ExecutionTrace, evaluation: Optional[SimulationEvaluation],
                     max_bytes: Optional[int] = None,
                     continuation: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Columns that change when a paused run is resumed."""
    cap = settings.max_run_bytes if max_bytes is None else max_bytes
    patch: dict[str, Any] = {
        "status": trace.status,
        "step_count": len(trace.steps),
        "trace": trace.model_dump(mode="json"),
        "evaluation": evaluation.model_dump(mode="json") if evaluation else None,
        "truncated": False,
        "continuation": continuation,   # None clears it once the run is no longer paused
    }
    if _size(patch) <= cap:
        return patch
    for step in patch["trace"]["steps"]:
        step["input"] = None
        step["output"] = None
    patch["truncated"] = True
    return patch if _size(patch) <= cap else None


def _enabled() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_role_key)


async def persist_run(
    user_id: str,
    workflow: Workflow,
    input_data: dict[str, Any],
    sim_settings: SimulationSettings,
    trace: ExecutionTrace,
    evaluation: Optional[SimulationEvaluation],
    continuation: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Store a run; returns its id, or None if it was not saved."""
    if not _enabled():
        return None
    try:
        record = build_run_record(user_id, workflow, input_data, sim_settings, trace, evaluation,
                                  continuation=continuation)
        if record is None:
            logger.warning("Run %s not stored: exceeds %d bytes even without step data",
                           trace.trace_id, settings.max_run_bytes)
            return None
        await db.insert_run(record)
        await _prune(user_id)
        return trace.trace_id
    except Exception as exc:
        logger.warning("Run %s not stored: %s", trace.trace_id, exc)
        return None


async def update_run(
    user_id: str,
    trace: ExecutionTrace,
    evaluation: Optional[SimulationEvaluation],
    continuation: Optional[dict[str, Any]] = None,
) -> bool:
    """Update a stored run after a resume. Scoped to the user, so it can never touch another user's row."""
    if not _enabled():
        return False
    try:
        patch = build_run_update(trace, evaluation, continuation=continuation)
        if patch is None:
            return False
        return await db.update_run(user_id, trace.trace_id, patch)
    except Exception as exc:
        logger.warning("Run %s not updated: %s", trace.trace_id, exc)
        return False


async def load_paused(user_id: str, trace_id: str) -> bool:
    """Make a paused run resumable in this process by rebuilding it from its stored row.

    Needed on Lambda, where the resume request often reaches a different container than the
    one that paused. Scoped to ``user_id``: another user's run is never loaded.
    """
    if not _enabled():
        return False
    try:
        row = await db.get_run(user_id, trace_id)
        if not row or row.get("status") != "paused" or not row.get("continuation"):
            return False
        return simulator.restore_paused_state(
            ExecutionTrace.model_validate(row["trace"]),
            Workflow.model_validate(row["workflow"]),
            SimulationSettings.model_validate(row["settings"]),
            row["continuation"],
        )
    except Exception as exc:
        logger.warning("Paused run %s could not be restored: %s", trace_id, exc)
        return False


async def _prune(user_id: str) -> None:
    try:
        cutoff = None
        if settings.run_retention_days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.run_retention_days)).isoformat()
        await db.prune_runs(user_id, settings.max_runs_per_user, cutoff)
    except Exception as exc:  # retention is housekeeping; never surface it
        logger.warning("Run pruning failed for user %s: %s", user_id, exc)
