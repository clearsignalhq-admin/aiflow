"""Download a workflow as a runnable project (Task 53)."""
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.api.deps import ApprovedUser
from app.core import supabase_client as db
from app.models.workflow import Workflow
from app.services.langgraph_exporter import ExportError, LangGraphExporter

router = APIRouter(prefix="/api")


class ExportLangGraphRequest(BaseModel):
    workflow: Workflow
    suite_id: Optional[str] = Field(default=None, max_length=64)   # include this suite's cases as tests
    seed: int = Field(default=0, ge=0, le=2**31 - 1)               # the suite run seed the tests replay


@router.post("/workflows/export/langgraph")
async def export_langgraph(body: ExportLangGraphRequest, user: ApprovedUser):
    """A zip of a LangGraph Python project. Deterministic and free: no LLM is involved."""
    cases = None
    if body.suite_id:
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
        folder, data = LangGraphExporter().export_zip(body.workflow, cases, body.seed)
    except ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{folder}.zip"'},
    )
