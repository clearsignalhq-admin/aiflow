"""Apply suggested changes to a workflow (Task 59).

Every change is applied to a copy and kept only if all of its operations succeed and the result is still a sound
workflow (one START, at least one END, no edges to missing steps, within size limits). A change that fails is skipped
with a reason; the others still apply. Nothing here trusts where a change came from.
"""
from typing import Optional

from app.models.workflow import MAX_EDGES, MAX_NODES, NodeType, Position, Workflow, WorkflowEdge, WorkflowNode
from app.schemas.patch import (
    AddEdge,
    AddNode,
    ApplyResponse,
    Change,
    ChangeView,
    RemoveEdge,
    RemoveNode,
    SkippedChange,
    UpdateEdge,
    UpdateNode,
)

_COL, _ROW = 240, 130          # spacing used when placing new steps


class PatchError(ValueError):
    """An operation (and so its whole change) cannot be applied."""


# ── Placement ────────────────────────────────────────────────────────────────

def _free_position(nodes: list[WorkflowNode], near: Optional[WorkflowNode]) -> Position:
    """Next to ``near`` (or below the lowest step), nudged until it does not sit on another step."""
    if near is not None:
        x, y = near.position.x + _COL, near.position.y + _ROW // 2
    elif nodes:
        x, y = nodes[-1].position.x, max(n.position.y for n in nodes) + _ROW
    else:
        x, y = 300.0, 100.0
    taken = [(n.position.x, n.position.y) for n in nodes]
    while any(abs(x - tx) < 160 and abs(y - ty) < 70 for tx, ty in taken):
        y += _ROW // 2
    return Position(x=x, y=y)


# ── Applying one change ──────────────────────────────────────────────────────

def _apply_ops(workflow: Workflow, change: Change) -> tuple[Workflow, list[str]]:
    nodes = [n.model_copy(deep=True) for n in workflow.nodes]
    edges = [e.model_copy(deep=True) for e in workflow.edges]
    added: list[str] = []

    def find(node_id: str) -> WorkflowNode:
        node = next((n for n in nodes if n.id == node_id), None)
        if node is None:
            raise PatchError(f"There is no step with id '{node_id}'.")
        return node

    for op in change.ops:
        if isinstance(op, AddNode):
            if any(n.id == op.id for n in nodes):
                raise PatchError(f"A step with id '{op.id}' already exists.")
            if op.type == NodeType.START:
                raise PatchError("A workflow has exactly one START, so another cannot be added.")
            if len(nodes) >= MAX_NODES:
                raise PatchError(f"The workflow would exceed {MAX_NODES} steps.")
            near = next((n for n in nodes if n.id == op.near), None) if op.near else None
            nodes.append(WorkflowNode(
                id=op.id, type=op.type, name=op.name, config=dict(op.config),
                input_schema=op.input_schema, output_schema=op.output_schema, position=_free_position(nodes, near),
            ))
            added.append(op.id)

        elif isinstance(op, RemoveNode):
            node = find(op.id)
            if node.type == NodeType.START:
                raise PatchError("The START step cannot be removed.")
            if node.type == NodeType.END and sum(1 for n in nodes if n.type == NodeType.END) == 1:
                raise PatchError("The last END step cannot be removed.")
            nodes = [n for n in nodes if n.id != op.id]
            edges = [e for e in edges if e.source != op.id and e.target != op.id]

        elif isinstance(op, UpdateNode):
            node = find(op.id)
            if op.name is not None:
                node.name = op.name
            config = {k: v for k, v in node.config.items() if k not in op.config_unset}
            config.update(op.config_set)
            node.config = config
            if "input_schema" in op.model_fields_set:
                node.input_schema = op.input_schema
            if "output_schema" in op.model_fields_set:
                node.output_schema = op.output_schema

        elif isinstance(op, AddEdge):
            source, target = find(op.source), find(op.target)
            if source.type == NodeType.END:
                raise PatchError(f"'{source.name}' is an END step and cannot have outgoing connections.")
            if target.type == NodeType.START:
                raise PatchError("Nothing can connect into the START step.")
            if source.id == target.id:
                raise PatchError("A step cannot connect to itself.")
            if not any(e.source == op.source and e.target == op.target and e.condition == op.condition for e in edges):
                if len(edges) >= MAX_EDGES:
                    raise PatchError(f"The workflow would exceed {MAX_EDGES} connections.")
                edges.append(WorkflowEdge(source=op.source, target=op.target, condition=op.condition))

        elif isinstance(op, (RemoveEdge, UpdateEdge)):
            find(op.source), find(op.target)
            matching = [e for e in edges if e.source == op.source and e.target == op.target
                        and (op.condition is None or e.condition == op.condition)]
            if not matching:
                raise PatchError(f"There is no connection from '{op.source}' to '{op.target}'" + (f" labelled '{op.condition}'." if op.condition else "."))
            if isinstance(op, RemoveEdge):
                edges = [e for e in edges if e not in matching]
            else:
                for e in matching:
                    e.condition = op.set_condition

    starts = [n for n in nodes if n.type == NodeType.START]
    if len(starts) != 1 or not any(n.type == NodeType.END for n in nodes):
        raise PatchError("The result must keep exactly one START and at least one END.")
    try:
        result = Workflow(**{**workflow.model_dump(), "nodes": [n.model_dump() for n in nodes], "edges": [e.model_dump() for e in edges]})
    except ValueError as exc:
        raise PatchError(f"The result is not a valid workflow: {exc}") from None
    return result, added


def apply_changes(workflow: Workflow, changes: list[Change]) -> ApplyResponse:
    """Apply each change in order; a change that cannot be applied is skipped with the reason."""
    current = workflow
    applied: list[str] = []
    skipped: list[SkippedChange] = []
    added_ids: list[str] = []
    seen: set[str] = set()
    for change in changes:
        if change.id in seen:
            skipped.append(SkippedChange(id=change.id, reason="This change was listed more than once."))
            continue
        seen.add(change.id)
        try:
            current, added = _apply_ops(current, change)
        except PatchError as exc:
            skipped.append(SkippedChange(id=change.id, reason=str(exc)))
        else:
            applied.append(change.id)
            added_ids += added
    return ApplyResponse(workflow=current, applied=applied, skipped=skipped, added_node_ids=added_ids)


def check_applies(workflow: Workflow, change: Change) -> Optional[str]:
    """None if the change applies cleanly to ``workflow``, otherwise why not."""
    try:
        _apply_ops(workflow, change)
    except PatchError as exc:
        return str(exc)
    return None


# ── Describing a change ──────────────────────────────────────────────────────

def touched_nodes(change: Change) -> list[str]:
    ids: list[str] = []
    for op in change.ops:
        for key in ("id", "source", "target"):
            value = getattr(op, key, None)
            if value and value not in ids:
                ids.append(value)
    return ids


def describe(workflow: Workflow, change: Change) -> list[str]:
    """One plain sentence per operation, using step names."""
    names = {n.id: n.name for n in workflow.nodes}
    for op in change.ops:
        if isinstance(op, AddNode):
            names[op.id] = op.name

    def name(node_id: str) -> str:
        return f"“{names.get(node_id, node_id)}”"

    def label(text: Optional[str]) -> str:
        return f" (label: {text})" if text else ""

    lines: list[str] = []
    for op in change.ops:
        if isinstance(op, AddNode):
            lines.append(f"Add {op.type.value} step {name(op.id)}")
        elif isinstance(op, RemoveNode):
            lines.append(f"Remove step {name(op.id)} and its connections")
        elif isinstance(op, UpdateNode):
            parts = ([f"rename to “{op.name}”"] if op.name else []) \
                + [f"set {k}" for k in op.config_set] + [f"remove {k}" for k in op.config_unset] \
                + (["change the input schema"] if "input_schema" in op.model_fields_set else []) \
                + (["change the output schema"] if "output_schema" in op.model_fields_set else [])
            lines.append(f"Change {name(op.id)}: {', '.join(parts) or 'no changes'}")
        elif isinstance(op, AddEdge):
            lines.append(f"Connect {name(op.source)} → {name(op.target)}{label(op.condition)}")
        elif isinstance(op, RemoveEdge):
            lines.append(f"Remove the connection {name(op.source)} → {name(op.target)}{label(op.condition)}")
        elif isinstance(op, UpdateEdge):
            lines.append(f"Relabel {name(op.source)} → {name(op.target)}: {op.condition or '(none)'} → {op.set_condition or '(none)'}")
    return lines


def view(workflow: Workflow, change: Change) -> ChangeView:
    return ChangeView(**change.model_dump(), summary=describe(workflow, change), touches=touched_nodes(change))
