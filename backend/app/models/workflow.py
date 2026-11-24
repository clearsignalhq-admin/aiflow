from enum import Enum
from typing import Any, Optional
import json
import uuid

from pydantic import BaseModel, Field, field_validator

# ── Size limits (protect validate / simulate / evaluate / LLM prompts) ───────
MAX_NODES = 100
MAX_EDGES = 300
MAX_NAME_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5000
MAX_DICT_JSON_BYTES = 20_000      # per node.config / edge.metadata / workflow.metadata


def _check_dict_size(value: dict[str, Any], what: str) -> dict[str, Any]:
    try:
        size = len(json.dumps(value, default=str))
    except (TypeError, ValueError):
        raise ValueError(f"{what} is not JSON-serialisable")
    if size > MAX_DICT_JSON_BYTES:
        raise ValueError(f"{what} is too large ({size} bytes; max {MAX_DICT_JSON_BYTES})")
    return value


class NodeType(str, Enum):
    START = "START"
    END = "END"
    LLM = "LLM"
    TOOL = "TOOL"
    API = "API"
    DATABASE = "DATABASE"
    RAG = "RAG"
    CONDITION = "CONDITION"
    HITL = "HITL"
    TRANSFORM = "TRANSFORM"


class Position(BaseModel):
    x: float = 0.0
    y: float = 0.0


class WorkflowNode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), max_length=100)
    type: NodeType
    name: str = Field(max_length=MAX_NAME_LENGTH)
    position: Position = Field(default_factory=Position)
    config: dict[str, Any] = Field(default_factory=dict)
    # Optional data contracts (JSON-Schema subset, see app/services/schema_utils.py)
    input_schema: Optional[dict[str, Any]] = None
    output_schema: Optional[dict[str, Any]] = None

    @field_validator("input_schema", "output_schema")
    @classmethod
    def _schema_size(cls, v: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        return None if v is None else _check_dict_size(v, "Node schema")

    @field_validator("config")
    @classmethod
    def _config_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _check_dict_size(v, "Node config")


class WorkflowEdge(BaseModel):
    source: str = Field(max_length=100)
    target: str = Field(max_length=100)
    condition: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _metadata_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _check_dict_size(v, "Edge metadata")


class Workflow(BaseModel):
    version: str = "1.0"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(default="Untitled Workflow", max_length=MAX_NAME_LENGTH)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LENGTH)
    nodes: list[WorkflowNode] = Field(default_factory=list, max_length=MAX_NODES)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=MAX_EDGES)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _metadata_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _check_dict_size(v, "Workflow metadata")
