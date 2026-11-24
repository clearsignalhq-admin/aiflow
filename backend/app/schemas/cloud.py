"""Cloud workflows, versions and share links (Task 61)."""
from typing import Optional

from pydantic import BaseModel, Field

from app.models.workflow import MAX_NAME_LENGTH, Workflow
from app.schemas.suites import WorkflowDiff


class CloudWorkflowWrite(BaseModel):
    """Create (name required) or save (name optional: keeps the current one)."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    workflow: Workflow
    label: Optional[str] = Field(default=None, max_length=100)     # shown in the version list ("before refactor")


class CloudWorkflowSummary(BaseModel):
    id: str
    name: str
    version_count: int
    shared: bool
    updated_at: str


class CloudWorkflowDetail(CloudWorkflowSummary):
    workflow: Workflow
    share_token: Optional[str] = None
    new_version: bool = True        # False when a save changed nothing and so added no version


class VersionSummary(BaseModel):
    version: int
    label: Optional[str] = None
    created_at: str
    node_count: int
    edge_count: int


class VersionDetail(VersionSummary):
    workflow: Workflow


class VersionDiff(BaseModel):
    base_version: int
    head_version: Optional[int] = None      # None = the current copy
    diff: WorkflowDiff


class ShareInfo(BaseModel):
    share_token: Optional[str] = None


class SharedWorkflow(BaseModel):
    name: str
    workflow: Workflow
    shared_at: Optional[str] = None
