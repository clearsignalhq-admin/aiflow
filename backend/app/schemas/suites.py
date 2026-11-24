"""Request/response models for test suites (Task 50)."""
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.workflow import Workflow, _check_dict_size
from app.services.assertions import MAX_ASSERTIONS_PER_CASE, definition_problems

MAX_CASES_HARD_LIMIT = 200            # absolute ceiling; the per-tier cap is enforced in the route
MAX_SUITE_BYTES = 500_000             # whole suite document, cases + assertions


class Assertion(BaseModel):
    """One deterministic check. Which fields apply depends on ``type`` (see services/assertions.py)."""
    model_config = ConfigDict(extra="forbid")

    type: str
    label: Optional[str] = None
    path: Optional[str] = None
    value: Any = None
    op: Optional[str] = None
    values: Optional[list[Any]] = None
    output_schema: Optional[dict[str, Any]] = None
    expression: Optional[str] = None
    node_id: Optional[str] = None
    max_steps: Optional[int] = None

    @model_validator(mode="after")
    def _check_definition(self):
        # exclude_unset keeps "value was explicitly null" distinct from "value missing"
        problems = definition_problems(self.model_dump(exclude_unset=True))
        if problems:
            raise ValueError("; ".join(problems))
        return self


class SuiteCase(BaseModel):
    id: Optional[str] = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    input: dict[str, Any] = Field(default_factory=dict)
    assertions: list[Assertion] = Field(default_factory=list, max_length=MAX_ASSERTIONS_PER_CASE)
    tags: list[str] = Field(default_factory=list, max_length=10)
    seed: Optional[int] = Field(default=None, ge=0, le=2**31 - 1)

    @field_validator("input")
    @classmethod
    def _input_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _check_dict_size(v, "Case input")

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        if any(not isinstance(t, str) or not t.strip() or len(t) > 40 for t in v):
            raise ValueError("tags must be non-empty text of at most 40 characters")
        return v


class SuiteWrite(BaseModel):
    """Body of POST /suites and PUT /suites/{id}. ``workflow_id`` is only used on create."""
    name: str = Field(min_length=1, max_length=200)
    workflow_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    cases: list[SuiteCase] = Field(default_factory=list, max_length=MAX_CASES_HARD_LIMIT)


class SuiteSummary(BaseModel):
    id: str
    workflow_id: str
    name: str
    case_count: int
    updated_at: str


class SuiteDetail(BaseModel):
    id: str
    workflow_id: str
    name: str
    cases: list[SuiteCase]
    created_at: str
    updated_at: str


class SuiteList(BaseModel):
    suites: list[SuiteSummary]


# ── Runs ─────────────────────────────────────────────────────────────────────

class CreateSuiteRunRequest(BaseModel):
    workflow: Workflow
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    llm_mode: Literal["mock", "real"] = "mock"     # "real" calls the AI model and uses LLM-request allowance


class RunEstimate(BaseModel):
    """What a run would use, before it starts."""
    cases: int
    llm_mode: Literal["mock", "real"]
    llm_calls_per_case_max: int
    llm_calls_max: int
    cost_usd_max: float                       # rough: fixed per-call assumption, not a quote
    executions_needed: int
    executions_remaining: Optional[int] = None     # None = unlimited
    llm_requests_remaining: Optional[int] = None   # None = unlimited
    allowed: bool
    reason: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class CaseRef(BaseModel):
    id: str
    name: str


class AssertionOutcome(BaseModel):
    index: int
    type: str
    label: str
    passed: bool
    message: str


class CaseResult(BaseModel):
    case_id: str
    case_name: str
    status: Literal["passed", "failed", "error"]
    duration_ms: int
    llm_calls: int = 0                      # model calls this case made (real mode)
    error: Optional[str] = None
    error_node_id: Optional[str] = None
    assertion_results: list[AssertionOutcome] = Field(default_factory=list)
    output: Any = None
    path: list[str] = Field(default_factory=list)          # node ids in execution order
    edges_taken: list[str] = Field(default_factory=list)   # "source→target"
    warnings: list[str] = Field(default_factory=list)


class Coverage(BaseModel):
    node_visits: dict[str, int]
    never_visited: list[str]                 # node ids no case executed
    edges_taken: dict[str, int]
    edges_never_taken: list[dict[str, Optional[str]]]   # {source, target, label}
    node_failures: dict[str, int]            # failed/errored cases that executed (or broke at) each node


class RunReport(BaseModel):
    total: int
    completed: int
    passed: int
    failed: int
    errors: int
    pass_rate: Optional[float] = None        # passed / completed, None until a case has finished
    llm_calls: int = 0
    coverage: Coverage


class SuiteRunSummary(BaseModel):
    id: str
    suite_id: str
    status: Literal["running", "complete", "cancelled", "failed"]
    case_count: int
    passed: int = 0
    failed: int = 0
    errors: int = 0
    created_at: str
    finished_at: Optional[str] = None


class SuiteRunDetail(BaseModel):
    id: str
    suite_id: str
    status: Literal["running", "complete", "cancelled", "failed"]
    case_count: int
    seed: int
    llm_mode: Literal["mock", "real"] = "mock"
    cases: list[CaseRef]
    results: list[CaseResult]
    report: RunReport
    created_at: str
    finished_at: Optional[str] = None
    note: Optional[str] = None               # e.g. why a job was marked failed


class SuiteRunList(BaseModel):
    runs: list[SuiteRunSummary]



# ── Comparing two runs (Task 58) ─────────────────────────────────────────────

CaseChange = Literal["regressed", "fixed", "still_failing", "unchanged", "added", "removed", "incomplete"]


class AssertionChange(BaseModel):
    label: str
    type: str
    base_passed: Optional[bool] = None
    head_passed: Optional[bool] = None
    base_message: Optional[str] = None
    head_message: Optional[str] = None


class CaseComparison(BaseModel):
    case_id: str
    case_name: str
    change: CaseChange
    base_status: Optional[str] = None
    head_status: Optional[str] = None
    definition_changed: bool = False           # the case itself (input, checks, seed) was edited between the runs
    path_changed: bool = False
    nodes_added: list[str] = Field(default_factory=list)       # executed now, not before
    nodes_removed: list[str] = Field(default_factory=list)     # executed before, not now
    output_changed: bool = False
    assertion_changes: list[AssertionChange] = Field(default_factory=list)
    base_error: Optional[str] = None
    head_error: Optional[str] = None
    duration_delta_ms: Optional[int] = None
    llm_calls_delta: Optional[int] = None


class FieldChange(BaseModel):
    field: str
    before: Any = None
    after: Any = None


class NodeChange(BaseModel):
    node_id: str
    name: str
    change: Literal["added", "removed", "modified"]
    fields: list[FieldChange] = Field(default_factory=list)


class EdgeChange(BaseModel):
    source: str
    target: str
    source_name: str
    target_name: str
    label: Optional[str] = None
    change: Literal["added", "removed"]


class WorkflowDiff(BaseModel):
    nodes: list[NodeChange] = Field(default_factory=list)
    edges: list[EdgeChange] = Field(default_factory=list)
    changed: bool = False


class CoverageChange(BaseModel):
    nodes_newly_visited: list[str] = Field(default_factory=list)
    nodes_no_longer_visited: list[str] = Field(default_factory=list)
    edges_newly_taken: list[str] = Field(default_factory=list)
    edges_no_longer_taken: list[str] = Field(default_factory=list)


class RunSide(BaseModel):
    id: str
    created_at: str
    status: str
    llm_mode: Literal["mock", "real"] = "mock"
    seed: int
    case_count: int
    completed: int
    passed: int
    failed: int
    errors: int
    pass_rate: Optional[float] = None
    llm_calls: int = 0
    total_duration_ms: int = 0


class ComparisonSummary(BaseModel):
    regressed: int = 0
    fixed: int = 0
    still_failing: int = 0
    unchanged: int = 0
    added: int = 0
    removed: int = 0
    incomplete: int = 0
    pass_rate_delta: Optional[float] = None    # head minus base, as a fraction (0.2 = +20 points)


class RunComparison(BaseModel):
    base: RunSide
    head: RunSide
    verdict: Literal["regression", "improvement", "no_change"]
    summary: ComparisonSummary
    cases: list[CaseComparison]
    workflow: WorkflowDiff
    coverage: CoverageChange
    warnings: list[str] = Field(default_factory=list)
