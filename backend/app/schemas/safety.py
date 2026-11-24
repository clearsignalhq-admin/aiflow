"""Resilience drill and injection exposure report (Task 60)."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.workflow import Workflow
from app.schemas.simulation import FailureKind

Verdict = Literal["handled", "ignored", "halted"]


# ── Resilience drill ─────────────────────────────────────────────────────────

class ResilienceRequest(BaseModel):
    workflow: Workflow
    input: dict = Field(default_factory=dict)
    seed: int = 0


class DrillResult(BaseModel):
    node_id: str
    node_name: str
    node_type: str
    kind: FailureKind
    verdict: Verdict
    detail: str
    path: list[str] = Field(default_factory=list)        # step ids in the order they ran
    error: Optional[str] = None


class ResilienceSummary(BaseModel):
    handled: int = 0
    ignored: int = 0
    halted: int = 0
    total: int = 0


class ResilienceReport(BaseModel):
    baseline_status: str
    baseline_path: list[str]
    results: list[DrillResult]
    summary: ResilienceSummary
    not_reached: list[str] = Field(default_factory=list)      # steps that could fail but did not run with this input
    skipped: int = 0                                          # drills left out because the workflow has too many steps
    notes: list[str] = Field(default_factory=list)


# ── Injection exposure ───────────────────────────────────────────────────────

class ExposureSource(BaseModel):
    node_id: str
    name: str
    kind: str                       # "user input" | "retrieved documents" | "API response" | ...


class ExposureSink(BaseModel):
    node_id: str
    name: str
    action: str                     # "writes through an API" | "writes to a database" | "calls a tool"
    gated: bool                     # a human review sits between the model and this step on every path


class Exposure(BaseModel):
    node_id: str                    # the model step
    name: str
    severity: Literal["high", "medium", "low"]
    sources: list[ExposureSource]
    sinks: list[ExposureSink]
    message: str
    advice: str


class ExposureReport(BaseModel):
    exposures: list[Exposure]
    llm_steps: int
    notes: list[str] = Field(default_factory=list)
