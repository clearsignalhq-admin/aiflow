"""Download a workflow as a runnable project (Task 53)."""
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.api.deps import ApprovedUser
from app.core import supabase_client as db
from app.models.workflow import Workflow
from app.services.exporters import TARGETS, export_zip
from app.services.langgraph_exporter import ExportError
from app.services.langgraph_importer import import_langgraph

router = APIRouter(prefix="/api")


class ExportRequest(BaseModel):
    workflow: Workflow
    target: Literal["langgraph", "python", "mcp"] = "langgraph"
    suite_id: Optional[str] = Field(default=None, max_length=64)   # include this suite's cases as tests
    seed: int = Field(default=0, ge=0, le=2**31 - 1)               # the suite run seed the tests replay


async def _export(body: ExportRequest, user) -> Response:
    cases = None
    if body.suite_id:
        if not TARGETS[body.target][2]:
            raise HTTPException(status_code=422, detail=f"{TARGETS[body.target][0]} exports do not include tests from a suite.")
        try:
            suite_id = str(uuid.UUID(body.suite_id))
        except ValueError:
            raise HTTPException(status_code=404, detail="Suite not found.")
        suite = await db.get_suite(user.id, suite_id)
        if suite is None:
            raise HTTPException(status_code=404, detail="Suite not found.")
        if suite["workflow_id"] != body.workflow.id:
            raise HTTPException(status_code=422, detail="That suite belongs to a different workflow.")
        cases = suite.get("cases") or []

    try:
        folder, data = export_zip(body.workflow, body.target, cases, body.seed)
    except ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{folder}.zip"'},
    )


@router.post("/workflows/export")
async def export_project(body: ExportRequest, user: ApprovedUser):
    """A zip of a runnable project for the chosen target. Deterministic and free: no LLM is involved."""
    return await _export(body, user)


@router.get("/workflows/export/targets")
async def export_targets(user: ApprovedUser):
    return {"targets": [{"id": k, "label": v[0], "description": v[1], "supports_tests": v[2]} for k, v in TARGETS.items()]}


@router.post("/workflows/export/langgraph")
async def export_langgraph(body: ExportRequest, user: ApprovedUser):
    """Kept for existing callers: the same as POST /workflows/export with target "langgraph"."""
    return await _export(body.model_copy(update={"target": "langgraph"}), user)


class ImportLangGraphRequest(BaseModel):
    """Source files of a LangGraph project, by path. They are parsed, never run."""
    files: dict[str, str] = Field(max_length=20)


@router.post("/workflows/import/langgraph")
async def import_langgraph_project(body: ImportLangGraphRequest, user: ApprovedUser):
    result = import_langgraph(body.files)
    if result.workflow is None:
        raise HTTPException(status_code=422, detail=" ".join(result.errors) or "The code could not be imported.")
    return {"workflow": result.workflow, "warnings": result.warnings, "mode": result.mode}
