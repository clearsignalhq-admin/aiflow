from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field
import uuid

from app.models.workflow import Workflow


class LLMMode(str, Enum):
    MOCK = "mock"
    REAL = "real"


class HITLMode(str, Enum):
    AUTO_APPROVE = "auto-approve"
    PAUSE = "pause"


class ConditionMode(str, Enum):
    USER_PICK = "user-pick"
    EXPRESSION = "expression"
    RANDOM = "random"


class DisplayMode(str, Enum):
    ANIMATED = "animated"
    INSTANT = "instant"
    MANUAL = "manual"


class SimulationSettings(BaseModel):
    llm_mode: LLMMode = LLMMode.MOCK
    hitl_mode: HITLMode = HITLMode.AUTO_APPROVE
    condition_mode: ConditionMode = ConditionMode.EXPRESSION
    display_mode: DisplayMode = DisplayMode.ANIMATED
    animation_delay_ms: int = 600
    evaluate: bool = False
    seed: int = 0   # seeds schema-generated mock data so runs are reproducible


class NodeExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    WAITING = "waiting"


class NodeExecution(BaseModel):
    node_id: str
    node_name: str
    node_type: str
    status: NodeExecutionStatus
    started_at: str
    completed_at: Optional[str] = None
    input: Any = None
    output: Any = None
    error: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    next_ids: list[str] = Field(default_factory=list)   # targets of the edges actually followed from this node


class ChoiceOption(BaseModel):
    target_id: str
    target_name: str
    label: Optional[str] = None


class PendingChoice(BaseModel):
    """A CONDITION node waiting for the user to pick an outgoing edge (user-pick mode)."""
    node_id: str
    options: list[ChoiceOption]


class ExecutionTrace(BaseModel):
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str
    workflow_name: str
    started_at: str
    completed_at: Optional[str] = None
    status: Literal["running", "paused", "complete", "error"] = "complete"
    steps: list[NodeExecution] = Field(default_factory=list)
    pending_choice: Optional[PendingChoice] = None


class SimulationEvaluation(BaseModel):
    score: int                      # 1–10
    summary: str
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    source: Literal["llm", "mock"] = "mock"
    fallback_reason: Optional[str] = None   # set when a real-LLM evaluation fell back to mock


class SimulateWorkflowRequest(BaseModel):
    workflow: Workflow
    input: dict[str, Any] = Field(default_factory=dict)
    settings: SimulationSettings = Field(default_factory=SimulationSettings)


class SimulateWorkflowResponse(BaseModel):
    trace: ExecutionTrace
    evaluation: Optional[SimulationEvaluation] = None
    run_id: Optional[str] = None   # set when the run was persisted (see services/run_persistence.py)


class ResumeSimulationRequest(BaseModel):
    trace_id: str
    node_id: str
    decision: Literal["approve", "reject", "choose"]
    edge_target: Optional[str] = None   # required when decision == "choose"
