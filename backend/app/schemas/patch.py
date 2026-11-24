"""Edit operations, suggested changes and their API shapes (Task 59).

A *change* is one suggestion a person can accept or dismiss on its own. It is a short list of operations that are
applied together or not at all. Operations are plain data, so a change can come from a deterministic fix or from
the AI, and is validated the same way either way.
"""
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.workflow import MAX_NAME_LENGTH, NodeType, Workflow, _check_dict_size

MAX_OPS_PER_CHANGE = 20
MAX_CHANGES = 20
NODE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")      # an operation with unknown fields is rejected, not guessed at


class AddNode(_Op):
    op: Literal["add_node"]
    id: str = Field(pattern=NODE_ID_PATTERN)
    type: NodeType
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    config: dict[str, Any] = Field(default_factory=dict)
    input_schema: Optional[dict[str, Any]] = None
    output_schema: Optional[dict[str, Any]] = None
    near: Optional[str] = Field(default=None, max_length=100)   # place the new step next to this one

    @field_validator("config", "input_schema", "output_schema")
    @classmethod
    def _size(cls, v):
        return None if v is None else _check_dict_size(v, "Step data")


class RemoveNode(_Op):
    op: Literal["remove_node"]
    id: str = Field(max_length=100)


class UpdateNode(_Op):
    """Change a step. Only the fields that are present are touched; a present ``output_schema: null`` clears it."""
    op: Literal["update_node"]
    id: str = Field(max_length=100)
    name: Optional[str] = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    config_set: dict[str, Any] = Field(default_factory=dict)
    config_unset: list[str] = Field(default_factory=list, max_length=50)
    input_schema: Optional[dict[str, Any]] = None
    output_schema: Optional[dict[str, Any]] = None

    @field_validator("config_set", "input_schema", "output_schema")
    @classmethod
    def _size(cls, v):
        return None if v is None else _check_dict_size(v, "Step data")


class AddEdge(_Op):
    op: Literal["add_edge"]
    source: str = Field(max_length=100)
    target: str = Field(max_length=100)
    condition: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)


class RemoveEdge(_Op):
    """Remove the edge(s) from source to target. With ``condition`` only the edge with that label; without, all of them."""
    op: Literal["remove_edge"]
    source: str = Field(max_length=100)
    target: str = Field(max_length=100)
    condition: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)


class UpdateEdge(_Op):
    """Change the label of the edge(s) from source to target (matched by ``condition`` if given)."""
    op: Literal["update_edge"]
    source: str = Field(max_length=100)
    target: str = Field(max_length=100)
    condition: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)
    set_condition: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)


Operation = Annotated[Union[AddNode, RemoveNode, UpdateNode, AddEdge, RemoveEdge, UpdateEdge], Field(discriminator="op")]


class Change(BaseModel):
    # Unknown top-level fields are ignored so a suggestion (with its display fields) can be posted back as is;
    # the operations inside stay strict.
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    rationale: str = Field(default="", max_length=1000)
    source: str = Field(default="", max_length=60)             # e.g. "lint:no-failure-branch" or "ai"
    ops: list[Operation] = Field(min_length=1, max_length=MAX_OPS_PER_CHANGE)


class ChangeView(Change):
    """A change as shown to the user: the operations plus what they would do, in words, and which steps they touch."""
    summary: list[str] = Field(default_factory=list)
    touches: list[str] = Field(default_factory=list)           # step ids, existing or new, for highlighting on the canvas


# ── Requests and responses ───────────────────────────────────────────────────

class FixesRequest(BaseModel):
    workflow: Workflow


class FixesResponse(BaseModel):
    changes: list[ChangeView]


class SuggestRequest(BaseModel):
    workflow: Workflow
    instruction: str = Field(min_length=3, max_length=1000)


class SuggestResponse(BaseModel):
    summary: str
    changes: list[ChangeView]
    discarded: list[str] = Field(default_factory=list)         # suggestions the AI made that could not be used, and why


class ApplyRequest(BaseModel):
    workflow: Workflow
    changes: list[Change] = Field(min_length=1, max_length=MAX_CHANGES)


class SkippedChange(BaseModel):
    id: str
    reason: str


class ApplyResponse(BaseModel):
    workflow: Workflow
    applied: list[str]
    skipped: list[SkippedChange]
    added_node_ids: list[str] = Field(default_factory=list)    # so the UI can show what is new
