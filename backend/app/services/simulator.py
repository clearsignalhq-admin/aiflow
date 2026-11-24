"""Workflow simulation engine.

Executes a Workflow as a mock simulation and returns an ExecutionTrace.
All node handlers produce deterministic mock output — no real LLM or API
calls are made.

Cycle detection uses DFS three-colour marking. Graph traversal uses BFS
from the START node; branching at CONDITION nodes is controlled by
SimulationSettings.condition_mode.

HITL pause/resume: when hitl_mode='pause' the BFS halts at the first HITL
node, persists the continuation state in an in-memory store, and returns
a trace with status='paused'. The caller then calls resume_simulation() to
continue from where it left off.
"""
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.models.workflow import NodeType, Workflow, WorkflowEdge
from app.schemas.simulation import (
    ChoiceOption,
    ConditionMode,
    ExecutionTrace,
    HITLMode,
    NodeExecution,
    NodeExecutionStatus,
    PendingChoice,
    SimulationSettings,
)
from app.services import node_handlers


class SimulationError(Exception):
    pass


class InvalidResumeError(SimulationError):
    """The paused simulation exists, but the resume request is not valid for it."""


# ── In-memory paused-simulation store ────────────────────────────────────────
# Not thread-safe; sufficient for single-process MVP2 usage.

@dataclass
class _PausedState:
    trace: ExecutionTrace
    workflow: Workflow
    settings: SimulationSettings
    paused_node_id: str
    continuation_queue: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    visited: set[str] = field(default_factory=set)
    kind: str = "hitl"                      # "hitl" | "condition"
    choice_targets: set[str] = field(default_factory=set)   # valid edge targets for kind == "condition"
    condition_output: dict[str, Any] | None = None           # data to pass down the chosen branch


_paused_store: dict[str, _PausedState] = {}


# ── Public entry points ───────────────────────────────────────────────────────

async def simulate(
    workflow: Workflow,
    input_data: dict[str, Any],
    settings: SimulationSettings,
) -> ExecutionTrace:
    _validate_for_simulation(workflow)

    node_by_id = {n.id: n for n in workflow.nodes}
    edges_from: dict[str, list[WorkflowEdge]] = defaultdict(list)
    for edge in workflow.edges:
        edges_from[edge.source].append(edge)

    start_node = next(n for n in workflow.nodes if n.type == NodeType.START)

    trace = ExecutionTrace(
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        started_at=_now(),
        status="running",
    )

    queue: deque[tuple[str, dict[str, Any]]] = deque([(start_node.id, input_data)])
    return await _run_bfs(trace, workflow, settings, node_by_id, edges_from, queue, set())


def get_paused_settings(trace_id: str) -> tuple[Workflow, SimulationSettings] | None:
    """Return (workflow, settings) for a paused trace without consuming it, or None."""
    paused = _paused_store.get(trace_id)
    if paused is None:
        return None
    return paused.workflow, paused.settings


_PAUSE_KINDS = {"hitl", "condition"}
_CONTINUATION_VERSION = 1


def export_paused_state(trace_id: str) -> dict[str, Any] | None:
    """JSON-serialisable continuation of a paused trace, or None if it is not paused here.

    Stored with the persisted run so a different process can resume it (Lambda containers
    do not share memory). The trace, workflow and settings are stored separately by the run record.
    """
    paused = _paused_store.get(trace_id)
    if paused is None:
        return None
    return {
        "v": _CONTINUATION_VERSION,
        "kind": paused.kind,
        "paused_node_id": paused.paused_node_id,
        "queue": [[node_id, data] for node_id, data in paused.continuation_queue],
        "visited": sorted(paused.visited),
        "choice_targets": sorted(paused.choice_targets),
        "condition_output": paused.condition_output,
    }


def restore_paused_state(
    trace: ExecutionTrace,
    workflow: Workflow,
    settings: SimulationSettings,
    continuation: Any,
) -> bool:
    """Rebuild a paused simulation from stored data. Returns False (and stores nothing) if it is not usable."""
    if not isinstance(continuation, dict) or continuation.get("v") != _CONTINUATION_VERSION:
        return False
    if trace.status != "paused":
        return False
    node_ids = {n.id for n in workflow.nodes}
    kind = continuation.get("kind")
    paused_node_id = continuation.get("paused_node_id")
    queue = continuation.get("queue")
    visited = continuation.get("visited")
    targets = continuation.get("choice_targets", [])
    if kind not in _PAUSE_KINDS or paused_node_id not in node_ids:
        return False
    if not isinstance(queue, list) or not isinstance(visited, list) or not isinstance(targets, list):
        return False
    parsed_queue: list[tuple[str, dict[str, Any]]] = []
    for entry in queue:
        if not (isinstance(entry, list) and len(entry) == 2 and entry[0] in node_ids and isinstance(entry[1], dict)):
            return False
        parsed_queue.append((entry[0], entry[1]))
    if not all(isinstance(v, str) and v in node_ids for v in visited):
        return False
    if not all(isinstance(t, str) and t in node_ids for t in targets):
        return False
    condition_output = continuation.get("condition_output")
    if condition_output is not None and not isinstance(condition_output, dict):
        return False
    if not any(s.node_id == paused_node_id and s.status == NodeExecutionStatus.WAITING for s in trace.steps):
        return False

    _paused_store[trace.trace_id] = _PausedState(
        trace=trace,
        workflow=workflow,
        settings=settings,
        paused_node_id=paused_node_id,
        continuation_queue=parsed_queue,
        visited=set(visited),
        kind=kind,
        choice_targets=set(targets),
        condition_output=condition_output,
    )
    return True


async def resume_simulation(
    trace_id: str,
    node_id: str,
    decision: str,
    edge_target: str | None = None,
) -> ExecutionTrace:
    """Resume a paused simulation.

    HITL pauses take decision 'approve' | 'reject'. CONDITION pauses (user-pick mode)
    take decision 'choose' plus the chosen ``edge_target`` node id.
    """
    paused = _paused_store.get(trace_id)
    if not paused:
        raise SimulationError(f"No paused simulation found with trace_id '{trace_id}'.")
    if paused.paused_node_id != node_id:
        raise SimulationError(
            f"Node '{node_id}' is not the paused {'condition' if paused.kind == 'condition' else 'HITL'} node "
            f"(expected '{paused.paused_node_id}')."
        )

    # Validate before consuming the paused state, so a bad request can be retried.
    if paused.kind == "condition":
        if decision != "choose":
            raise InvalidResumeError("This simulation is waiting for an edge choice (decision 'choose').")
        if edge_target not in paused.choice_targets:
            raise InvalidResumeError(f"'{edge_target}' is not one of the available branches.")
    elif decision not in ("approve", "reject"):
        raise InvalidResumeError("This simulation is waiting for 'approve' or 'reject'.")

    del _paused_store[trace_id]

    node_by_id = {n.id: n for n in paused.workflow.nodes}
    edges_from: dict[str, list[WorkflowEdge]] = defaultdict(list)
    for edge in paused.workflow.edges:
        edges_from[edge.source].append(edge)

    if paused.kind == "condition":
        waiting_step = next(
            s for s in paused.trace.steps
            if s.node_id == node_id and s.status == NodeExecutionStatus.WAITING
        )
        waiting_step.status = NodeExecutionStatus.SUCCESS
        waiting_step.completed_at = _now()
        chosen_label = next(
            (o.label for o in (paused.trace.pending_choice.options if paused.trace.pending_choice else [])
             if o.target_id == edge_target),
            None,
        )
        waiting_step.warnings.append(
            f"User chose branch '{chosen_label or edge_target}'."
        )
        paused.trace.pending_choice = None
        # condition_output survives step-data truncation of a stored run; step.output is the fallback.
        branch_data = paused.condition_output if paused.condition_output is not None else (waiting_step.output or {})
        successors = [(edge_target, branch_data)]
    else:
        hitl_output: dict[str, Any] = {
            "approved": decision == "approve",
            "reviewer": "human",
            "decision": decision,
        }
        # Promote the waiting step to success now that we have the decision.
        for step in paused.trace.steps:
            if step.node_id == node_id and step.status == NodeExecutionStatus.WAITING:
                step.status = NodeExecutionStatus.SUCCESS
                step.output = hitl_output
                step.completed_at = _now()
                break
        # Queue HITL successors (not yet visited).
        successors = [
            (edge.target, hitl_output)
            for edge in edges_from.get(node_id, [])
            if edge.target not in paused.visited and edge.target in node_by_id
        ]

    queue: deque[tuple[str, dict[str, Any]]] = deque(successors + paused.continuation_queue)

    paused.trace.status = "running"
    return await _run_bfs(
        paused.trace,
        paused.workflow,
        paused.settings,
        node_by_id,
        edges_from,
        queue,
        paused.visited,
    )


# ── Core BFS loop ─────────────────────────────────────────────────────────────

async def _run_bfs(
    trace: ExecutionTrace,
    workflow: Workflow,
    settings: SimulationSettings,
    node_by_id: dict[str, Any],
    edges_from: dict[str, list[WorkflowEdge]],
    queue: deque[tuple[str, dict[str, Any]]],
    visited: set[str],
) -> ExecutionTrace:
    while queue:
        node_id, data = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)

        node = node_by_id[node_id]
        step_start = _now()

        # HITL pause: halt before dispatching, store continuation for resume.
        if node.type == NodeType.HITL and settings.hitl_mode == HITLMode.PAUSE:
            step = NodeExecution(
                node_id=node.id,
                node_name=node.name,
                node_type=node.type.value,
                status=NodeExecutionStatus.WAITING,
                started_at=step_start,
                input=data,
            )
            trace.steps.append(step)
            trace.status = "paused"
            trace.completed_at = _now()
            _paused_store[trace.trace_id] = _PausedState(
                trace=trace,
                workflow=workflow,
                settings=settings,
                paused_node_id=node.id,
                continuation_queue=list(queue),
                visited=visited,
            )
            return trace

        try:
            output = await node_handlers.dispatch(node, data, settings)
            step = NodeExecution(
                node_id=node.id,
                node_name=node.name,
                node_type=node.type.value,
                status=NodeExecutionStatus.SUCCESS,
                started_at=step_start,
                completed_at=_now(),
                input=data,
                output=output,
            )
        except Exception as exc:
            step = NodeExecution(
                node_id=node.id,
                node_name=node.name,
                node_type=node.type.value,
                status=NodeExecutionStatus.ERROR,
                started_at=step_start,
                completed_at=_now(),
                input=data,
                error=str(exc),
            )
            trace.steps.append(step)
            trace.status = "error"
            trace.completed_at = _now()
            return trace

        trace.steps.append(step)

        if node.type == NodeType.END:
            continue

        outgoing = edges_from.get(node.id, [])

        # user-pick: pause at a real decision and let the caller choose the branch.
        if node.type == NodeType.CONDITION and settings.condition_mode == ConditionMode.USER_PICK:
            options = [e for e in outgoing if e.target in node_by_id]
            if len(options) > 1:
                step.status = NodeExecutionStatus.WAITING
                step.completed_at = None
                trace.status = "paused"
                trace.completed_at = _now()
                trace.pending_choice = PendingChoice(
                    node_id=node.id,
                    options=[
                        ChoiceOption(target_id=e.target, target_name=node_by_id[e.target].name, label=e.condition)
                        for e in options
                    ],
                )
                _paused_store[trace.trace_id] = _PausedState(
                    trace=trace,
                    workflow=workflow,
                    settings=settings,
                    paused_node_id=node.id,
                    continuation_queue=list(queue),
                    visited=visited,
                    kind="condition",
                    choice_targets={e.target for e in options},
                    condition_output=output,
                )
                return trace

        if node.type == NodeType.CONDITION:
            chosen, routing_warnings = node_handlers.select_condition_edges(node, outgoing, output, settings)
            step.warnings.extend(routing_warnings)
        else:
            chosen = outgoing

        step.next_ids = [e.target for e in chosen if e.target in node_by_id]
        for edge in chosen:
            if edge.target not in visited and edge.target in node_by_id:
                queue.append((edge.target, output))

    trace.status = "complete"
    trace.completed_at = _now()
    return trace


# ── Validation ────────────────────────────────────────────────────────────────

def validate_for_simulation(workflow: Workflow) -> None:
    """Raise SimulationError if the workflow cannot be simulated (no START/END, bad edges, cycle)."""
    _validate_for_simulation(workflow)


def _validate_for_simulation(workflow: Workflow) -> None:
    node_ids = {n.id for n in workflow.nodes}

    start_nodes = [n for n in workflow.nodes if n.type == NodeType.START]
    if not start_nodes:
        raise SimulationError("Workflow must have a START node.")
    if len(start_nodes) > 1:
        raise SimulationError(f"Workflow has {len(start_nodes)} START nodes; exactly one is required.")

    end_nodes = [n for n in workflow.nodes if n.type == NodeType.END]
    if not end_nodes:
        raise SimulationError("Workflow must have at least one END node.")

    for edge in workflow.edges:
        if edge.source not in node_ids:
            raise SimulationError(f"Edge references unknown source node: '{edge.source}'")
        if edge.target not in node_ids:
            raise SimulationError(f"Edge references unknown target node: '{edge.target}'")

    if _has_cycle(workflow):
        raise SimulationError("Workflow contains a cycle; simulation requires a DAG.")


def _has_cycle(workflow: Workflow) -> bool:
    edges_from: dict[str, list[str]] = defaultdict(list)
    for edge in workflow.edges:
        edges_from[edge.source].append(edge.target)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n.id: WHITE for n in workflow.nodes}

    def dfs(node_id: str) -> bool:
        color[node_id] = GRAY
        for neighbor in edges_from.get(node_id, []):
            if color.get(neighbor) == GRAY:
                return True
            if color.get(neighbor) == WHITE and dfs(neighbor):
                return True
        color[node_id] = BLACK
        return False

    return any(
        color[n.id] == WHITE and dfs(n.id)
        for n in workflow.nodes
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
