"""Cloud workflows: save, version history, diff, restore, and read-only share links (Task 61)."""
import json
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.api.deps import ApprovedUser
from app.core import supabase_client as db
from app.core.config import settings
from app.core.limiter import limiter
from app.models.workflow import Workflow
from app.schemas.cloud import (
    CloudWorkflowDetail,
    CloudWorkflowSummary,
    CloudWorkflowWrite,
    ShareInfo,
    SharedWorkflow,
    VersionDetail,
    VersionDiff,
    VersionSummary,
)
from app.services.run_comparison import diff_workflows

router = APIRouter(prefix="/api")

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


def _uuid(value: str, message: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(status_code=404, detail=message) from None


def _canon(workflow: Any) -> str:
    return json.dumps(workflow, sort_keys=True, default=str)


def _summary(row: dict[str, Any]) -> CloudWorkflowSummary:
    return CloudWorkflowSummary(id=row["id"], name=row["name"], version_count=row["version_count"],
                                shared=bool(row.get("share_token")), updated_at=row["updated_at"])


def _detail(row: dict[str, Any], new_version: bool = True) -> CloudWorkflowDetail:
    return CloudWorkflowDetail(**_summary(row).model_dump(), workflow=Workflow(**row["workflow"]),
                               share_token=row.get("share_token"), new_version=new_version)


def _version_summary(row: dict[str, Any]) -> VersionSummary:
    wf = row["workflow"]
    return VersionSummary(version=row["version"], label=row.get("label"), created_at=row["created_at"],
                          node_count=len(wf.get("nodes", [])), edge_count=len(wf.get("edges", [])))


async def _owned(user, workflow_id: str) -> dict[str, Any]:
    row = await db.get_cloud_workflow(user.id, _uuid(workflow_id, "Workflow not found."))
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return row


async def _add_version(user, row: dict[str, Any], workflow: dict[str, Any], label: Optional[str]) -> dict[str, Any]:
    """Append a version and make it current. The unique (workflow, version) key stops two racing saves colliding."""
    number = row["version_count"] + 1
    try:
        await db.insert_workflow_version({"workflow_id": row["id"], "user_id": user.id, "version": number,
                                          "label": label, "workflow": workflow})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 409:
            raise
        raise HTTPException(status_code=409, detail="This workflow was saved from somewhere else at the same moment. Reload it and try again.") from None
    updated = await db.update_cloud_workflow(user.id, row["id"], {"workflow": workflow, "version_count": number})
    await db.prune_workflow_versions(user.id, row["id"], settings.max_versions_per_workflow)
    if updated is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return updated


# ── Workflows ────────────────────────────────────────────────────────────────

@router.get("/cloud/workflows", response_model=list[CloudWorkflowSummary])
async def list_cloud_workflows(user: ApprovedUser):
    return [_summary(r) for r in await db.list_cloud_workflows(user.id)]


@router.post("/cloud/workflows", response_model=CloudWorkflowDetail, status_code=status.HTTP_201_CREATED)
async def create_cloud_workflow(body: CloudWorkflowWrite, user: ApprovedUser):
    if await db.count_cloud_workflows(user.id) >= settings.max_cloud_workflows_per_user:
        raise HTTPException(status_code=409, detail=f"You can keep at most {settings.max_cloud_workflows_per_user} workflows in the cloud. Delete one first.")
    data = body.workflow.model_dump(mode="json")
    row = await db.insert_cloud_workflow({"user_id": user.id, "name": (body.name or body.workflow.name), "workflow": data, "version_count": 1})
    await db.insert_workflow_version({"workflow_id": row["id"], "user_id": user.id, "version": 1, "label": body.label, "workflow": data})
    return _detail(row)


@router.get("/cloud/workflows/{workflow_id}", response_model=CloudWorkflowDetail)
async def get_cloud_workflow(workflow_id: str, user: ApprovedUser):
    return _detail(await _owned(user, workflow_id))


@router.put("/cloud/workflows/{workflow_id}", response_model=CloudWorkflowDetail)
async def save_cloud_workflow(workflow_id: str, body: CloudWorkflowWrite, user: ApprovedUser):
    """Save the workflow. If it is identical to the current copy no version is added (a rename still applies)."""
    row = await _owned(user, workflow_id)
    data = body.workflow.model_dump(mode="json")
    if _canon(data) == _canon(row["workflow"]):
        if body.name and body.name != row["name"]:
            row = await db.update_cloud_workflow(user.id, row["id"], {"name": body.name}) or row
        return _detail(row, new_version=False)
    row = await _add_version(user, row, data, body.label)
    if body.name and body.name != row["name"]:
        row = await db.update_cloud_workflow(user.id, row["id"], {"name": body.name}) or row
    return _detail(row)


@router.delete("/cloud/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cloud_workflow(workflow_id: str, user: ApprovedUser):
    if not await db.delete_cloud_workflow(user.id, _uuid(workflow_id, "Workflow not found.")):
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Versions ─────────────────────────────────────────────────────────────────

@router.get("/cloud/workflows/{workflow_id}/versions", response_model=list[VersionSummary])
async def list_versions(workflow_id: str, user: ApprovedUser):
    row = await _owned(user, workflow_id)
    return [_version_summary(v) for v in await db.list_workflow_versions(user.id, row["id"])]


async def _version(user, workflow_id: str, number: int) -> dict[str, Any]:
    row = await _owned(user, workflow_id)
    version = await db.get_workflow_version(user.id, row["id"], number)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found (older versions are removed once there are more than "
                                                    f"{settings.max_versions_per_workflow}).")
    return version


@router.get("/cloud/workflows/{workflow_id}/diff", response_model=VersionDiff)
async def diff_versions(workflow_id: str, user: ApprovedUser, base: int = Query(ge=1), head: Optional[int] = Query(default=None, ge=1)):
    """What changed from version ``base`` to version ``head`` (default: the current copy)."""
    base_row = await _version(user, workflow_id, base)
    if head is None:
        head_workflow = (await _owned(user, workflow_id))["workflow"]
    else:
        head_workflow = (await _version(user, workflow_id, head))["workflow"]
    return VersionDiff(base_version=base, head_version=head, diff=diff_workflows(base_row["workflow"], head_workflow))


@router.get("/cloud/workflows/{workflow_id}/versions/{number}", response_model=VersionDetail)
async def get_version(workflow_id: str, number: int, user: ApprovedUser):
    v = await _version(user, workflow_id, number)
    return VersionDetail(**_version_summary(v).model_dump(), workflow=Workflow(**v["workflow"]))


@router.post("/cloud/workflows/{workflow_id}/versions/{number}/restore", response_model=CloudWorkflowDetail)
async def restore_version(workflow_id: str, number: int, user: ApprovedUser):
    """Make an older version current by saving it as a new version, so history is never rewritten."""
    v = await _version(user, workflow_id, number)
    row = await _owned(user, workflow_id)
    if _canon(v["workflow"]) == _canon(row["workflow"]):
        return _detail(row, new_version=False)
    return _detail(await _add_version(user, row, v["workflow"], f"Restored from version {number}"))


# ── Sharing ──────────────────────────────────────────────────────────────────

@router.post("/cloud/workflows/{workflow_id}/share", response_model=ShareInfo)
async def share_workflow(workflow_id: str, user: ApprovedUser):
    """Turn on the read-only link (idempotent: an existing link keeps working)."""
    row = await _owned(user, workflow_id)
    if row.get("share_token"):
        return ShareInfo(share_token=row["share_token"])
    token = secrets.token_urlsafe(32)
    await db.update_cloud_workflow(user.id, row["id"], {"share_token": token, "shared_at": datetime.now(timezone.utc).isoformat()})
    return ShareInfo(share_token=token)


@router.delete("/cloud/workflows/{workflow_id}/share", response_model=ShareInfo)
async def stop_sharing(workflow_id: str, user: ApprovedUser):
    """Turn the link off; the old address stops working for good (sharing again makes a new one)."""
    row = await _owned(user, workflow_id)
    await db.update_cloud_workflow(user.id, row["id"], {"share_token": None, "shared_at": None})
    return ShareInfo(share_token=None)


@router.get("/shared/{token}", response_model=SharedWorkflow)
@limiter.limit("60/minute")
async def read_shared(request: Request, token: str):
    """Public, read-only. Returns only the name and the workflow, never who owns it."""
    if not _TOKEN.match(token):
        raise HTTPException(status_code=404, detail="This link is not valid or is no longer shared.")
    row = await db.get_cloud_workflow_by_token(token)
    if row is None:
        raise HTTPException(status_code=404, detail="This link is not valid or is no longer shared.")
    return SharedWorkflow(name=row["name"], workflow=Workflow(**row["workflow"]), shared_at=row.get("shared_at"))
