from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.models.workflow import Workflow


class LintSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class LintFinding(BaseModel):
    rule_id: str
    severity: LintSeverity
    node_id: Optional[str] = None
    message: str
    fix_hint: str = ""


class PathEstimate(BaseModel):
    """Rough per-path latency/cost estimate from fixed node-type heuristics."""
    node_ids: list[str]
    node_names: list[str]
    latency_ms: int
    cost_usd: float


class LintResult(BaseModel):
    findings: list[LintFinding] = Field(default_factory=list)
    estimates: list[PathEstimate] = Field(default_factory=list)


class LintWorkflowRequest(BaseModel):
    workflow: Workflow


class LintWorkflowResponse(LintResult):
    pass
