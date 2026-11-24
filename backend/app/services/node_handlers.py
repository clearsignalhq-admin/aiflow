"""Node handlers for workflow simulation.

Each handler receives the node, its input data, and simulation settings,
and returns a dict representing the node's output.

LLM nodes support two modes controlled by settings.llm_mode:
  mock — instant deterministic output, no API call
  real — calls the configured LLM provider (requires LLM_API_KEY)
"""
import asyncio
import json as _json
import random as _random
from typing import Any

from app.models.workflow import NodeType, WorkflowNode
from app.services import expressions
from app.schemas.simulation import SimulationSettings, LLMMode


async def dispatch(
    node: WorkflowNode,
    input_data: dict[str, Any],
    settings: SimulationSettings,
) -> dict[str, Any]:
    if node.type == NodeType.LLM:
        return await _handle_llm(node, input_data, settings)
    handlers = {
        NodeType.START: _handle_start,
        NodeType.END: _handle_end,
        NodeType.TOOL: _handle_tool,
        NodeType.API: _handle_api,
        NodeType.DATABASE: _handle_database,
        NodeType.RAG: _handle_rag,
        NodeType.CONDITION: _handle_condition,
        NodeType.HITL: _handle_hitl,
        NodeType.TRANSFORM: _handle_transform,
    }
    handler = handlers.get(node.type, _handle_unknown)
    return handler(node, input_data, settings)


# ── Handlers ─────────────────────────────────────────────────────────────────

def _handle_start(
    node: WorkflowNode, input_data: dict[str, Any], _settings: SimulationSettings
) -> dict[str, Any]:
    return dict(input_data)


def _handle_end(
    node: WorkflowNode, input_data: dict[str, Any], _settings: SimulationSettings
) -> dict[str, Any]:
    return {"result": input_data}


_LLM_NODE_TIMEOUT = 60.0  # seconds per LLM node in real mode


async def _handle_llm(
    node: WorkflowNode, input_data: dict[str, Any], settings: SimulationSettings
) -> dict[str, Any]:
    prompt = node.config.get("prompt", "You are a helpful AI assistant.")
    if settings.llm_mode == LLMMode.REAL:
        from app.providers.factory import get_provider
        provider = get_provider()
        user_msg = (
            "Input data:\n"
            + _json.dumps(input_data, indent=2, default=str)
            + "\n\nProcess the input according to your role and respond with a JSON object."
        )
        try:
            result = await asyncio.wait_for(
                provider.complete_json(prompt, user_msg),
                timeout=_LLM_NODE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"LLM node '{node.name}' timed out after {int(_LLM_NODE_TIMEOUT)}s. "
                "Check your API key and network, or switch to Mock mode."
            )
        return {"result": result, "node_id": node.id, "node_name": node.name}
    return {
        "result": f"Mock LLM output for prompt: {prompt[:80]}",
        "_mock": True,
        "node_id": node.id,
        "node_name": node.name,
    }


def _handle_tool(
    node: WorkflowNode, _input: dict[str, Any], _settings: SimulationSettings
) -> dict[str, Any]:
    return {"tool": node.name, "result": "mock tool output", "_mock": True}


def _handle_api(
    node: WorkflowNode, _input: dict[str, Any], _settings: SimulationSettings
) -> dict[str, Any]:
    return {"status": 200, "body": {"mock": True}, "_mock": True}


def _handle_database(
    node: WorkflowNode, _input: dict[str, Any], _settings: SimulationSettings
) -> dict[str, Any]:
    return {"rows": [], "_mock": True}


def _handle_rag(
    node: WorkflowNode, _input: dict[str, Any], _settings: SimulationSettings
) -> dict[str, Any]:
    return {"documents": [], "answer": "Mock RAG answer", "_mock": True}


def _handle_condition(
    node: WorkflowNode, input_data: dict[str, Any], _settings: SimulationSettings
) -> dict[str, Any]:
    """Returns the input unchanged; branch selection is handled by the simulator."""
    return dict(input_data)


def _handle_hitl(
    node: WorkflowNode, input_data: dict[str, Any], settings: SimulationSettings
) -> dict[str, Any]:
    # Pause behavior is implemented in Task 22 via the resume endpoint.
    # Auto-approve always produces an unbroken trace.
    return {"approved": True, "reviewer": "auto", "_mock": True}


def _handle_transform(
    node: WorkflowNode, input_data: dict[str, Any], _settings: SimulationSettings
) -> dict[str, Any]:
    return {**input_data, "_transformed": True}


def _handle_unknown(
    node: WorkflowNode, _input: dict[str, Any], _settings: SimulationSettings
) -> dict[str, Any]:
    return {"_mock": True, "node_type": str(node.type)}


# ── Edge selection for CONDITION nodes ───────────────────────────────────────

def select_condition_edges(
    node: WorkflowNode,
    outgoing_edges: list,
    input_data: dict[str, Any],
    settings: SimulationSettings,
) -> tuple[list, list[str]]:
    """Return ``(edges_to_follow, warnings)`` for a CONDITION node.

    Routing contract (expression mode):
      1. ``config.expression`` is evaluated by the safe evaluator in
         ``app.services.expressions`` against the node's input fields (plus
         ``input`` / ``output`` aliases for the whole dict).
      2. The result is matched, case-insensitively, against the outgoing edges'
         ``condition`` labels. ``True`` matches ``true``/``yes``, ``False``
         matches ``false``/``no``; any other value matches its string form.
      3. If nothing matches, edges labelled ``else``/``default``/``otherwise`` are used.
      4. If the expression is missing, fails, or matches no label, all outgoing
         edges are followed (so the whole graph is explored) and a warning is
         returned for the trace; failures are never silent.
    """
    from app.schemas.simulation import ConditionMode

    if not outgoing_edges:
        return [], []

    if settings.condition_mode == ConditionMode.RANDOM:
        return [_random.choice(outgoing_edges)], []

    if settings.condition_mode == ConditionMode.USER_PICK:
        # Full pause/resume is Task 43. Default to first edge for now.
        return outgoing_edges[:1], ["user-pick mode is not implemented yet; following the first edge."]

    # EXPRESSION mode
    expression = node.config.get("expression", "")
    if not isinstance(expression, str) or not expression.strip():
        return outgoing_edges, ["No expression configured; following all edges."]

    context = {**input_data, "input": input_data, "output": input_data}
    try:
        result = expressions.evaluate(expression, context)
    except expressions.ExpressionError as exc:
        return outgoing_edges, [f"Expression could not be evaluated ({exc}); following all edges."]

    candidates = expressions.label_candidates(result)
    matched = [e for e in outgoing_edges if expressions.normalise_label(e.condition) in candidates]
    if not matched:
        matched = [
            e for e in outgoing_edges
            if expressions.normalise_label(e.condition) in expressions.DEFAULT_LABELS
        ]
    if matched:
        return matched, []

    labels = sorted({str(e.condition) for e in outgoing_edges if e.condition})
    return outgoing_edges, [
        f"Expression result {result!r} matches no edge label ({', '.join(labels) or 'none set'}); following all edges."
    ]
