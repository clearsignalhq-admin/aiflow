"""One entry point for every export target (Task 56)."""
from typing import Any, Optional

from app.models.workflow import Workflow
from app.services.langgraph_exporter import ExportError, LangGraphExporter
from app.services.mcp_exporter import McpExporter

# id → (label, one-line description, whether suite cases become tests)
TARGETS: dict[str, tuple[str, str, bool]] = {
    "langgraph": ("LangGraph (Python)", "The whole workflow as a LangGraph project: graph, steps, routing, human-review pauses, CLI and tests.", True),
    "python": ("Plain Python", "The whole workflow with no framework: a small engine, the same steps and tests. Easiest to read and embed.", True),
    "mcp": ("MCP tools", "The workflow's tool, API, database and knowledge-search steps as an MCP server any MCP client can call.", False),
}


def export_zip(workflow: Workflow, target: str, cases: Optional[list[dict[str, Any]]] = None, run_seed: int = 0) -> tuple[str, bytes]:
    """``(folder name, zip bytes)`` for ``target``. Raises ExportError for an unknown target or an unexportable workflow."""
    if target == "mcp":
        return McpExporter().export_zip(workflow, cases, run_seed)
    if target in ("langgraph", "python"):
        return LangGraphExporter().export_zip(workflow, cases, run_seed, target)
    raise ExportError(f"Unknown export target {target!r}. Choose one of: {', '.join(TARGETS)}.")
