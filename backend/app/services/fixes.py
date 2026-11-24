"""Deterministic suggested fixes for lint findings (Task 59).

No AI involved: each fix is a fixed recipe for one finding, so the same workflow always gets the same suggestions and
they cost nothing. Fixes are only offered where the right answer is reasonably clear; findings that need judgement
(for example moving an approval before a write) are left to the AI "describe a change" box.
"""
import re
from typing import Optional

from app.models.workflow import NodeType, Workflow, WorkflowNode
from app.schemas.patch import (
    AddEdge, AddNode, Change, RemoveEdge, RemoveNode, UpdateEdge, UpdateNode,
)
from app.services import schema_utils
from app.services.linter import _referenced_fields, lint_workflow
from app.services.patching import check_applies

_TRUE_FALSE = ("true", "false")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()[:30] or "step"


def _unique(workflow: Workflow, base: str, taken: set[str]) -> str:
    existing = {n.id for n in workflow.nodes} | taken
    candidate, i = base, 2
    while candidate in existing:
        candidate, i = f"{base}-{i}", i + 1
    taken.add(candidate)
    return candidate


def _first_end(workflow: Workflow) -> Optional[WorkflowNode]:
    return next((n for n in workflow.nodes if n.type == NodeType.END), None)


def _node(workflow: Workflow, node_id: str) -> Optional[WorkflowNode]:
    return next((n for n in workflow.nodes if n.id == node_id), None)


def _schema_with(schema: Optional[dict], fields: list[str]) -> dict:
    """An output schema that also declares ``fields`` (existing properties are kept)."""
    base = dict(schema) if isinstance(schema, dict) else {"type": "object"}
    props = dict(base.get("properties") or {})
    for f in fields:
        props.setdefault(f, {})
    base["properties"] = props
    return base


def suggest_fixes(workflow: Workflow) -> list[Change]:
    """Changes that resolve current lint findings, each verified to apply cleanly to ``workflow``."""
    result = lint_workflow(workflow)
    changes: list[Change] = []
    taken: set[str] = set()
    end = _first_end(workflow)

    for f in result.findings:
        node = _node(workflow, f.node_id) if f.node_id else None
        if node is None:
            continue
        change: Optional[Change] = None
        fid = f"{f.rule_id}:{node.id}"
        src = f"lint:{f.rule_id}"

        if f.rule_id == "unreachable-node" and node.type != NodeType.START:
            change = Change(id=fid, source=src, title=f"Delete unreachable step “{node.name}”",
                            rationale="Nothing connects to it, so it never runs.", ops=[RemoveNode(op="remove_node", id=node.id)])

        elif f.rule_id == "dead-end" and end is not None:
            change = Change(id=fid, source=src, title=f"Connect “{node.name}” to “{end.name}”",
                            rationale="Nothing after this step finishes the workflow.",
                            ops=[AddEdge(op="add_edge", source=node.id, target=end.id)])

        elif f.rule_id == "condition-single-branch" and end is not None:
            edges = [e for e in workflow.edges if e.source == node.id]
            existing = (edges[0].condition or "").strip().lower() if edges else ""
            label = "false" if existing in ("true", "yes") else "true" if existing in ("false", "no") else "else"
            if not edges or edges[0].target != end.id:
                ops = []
                if edges and not existing:
                    ops.append(UpdateEdge(op="update_edge", source=node.id, target=edges[0].target, set_condition="true"))
                    label = "false"
                ops.append(AddEdge(op="add_edge", source=node.id, target=end.id, condition=label))
                change = Change(id=fid, source=src, title=f"Add a “{label}” branch from “{node.name}” to “{end.name}”",
                                rationale="A decision needs at least two outcomes; this gives the other case somewhere to go.", ops=ops)

        elif f.rule_id == "condition-unlabelled-branch":
            edges = [e for e in workflow.edges if e.source == node.id]
            labels = [(e.condition or "").strip() for e in edges]
            if len(edges) == 2 and labels.count("") >= 1:
                other = labels[1] if labels[0] == "" else labels[0]
                if labels == ["", ""]:
                    new = ["true", "false"]
                elif other.lower() in ("true", "yes"):
                    new = ["false" if other.lower() == "true" else "no"]
                elif other.lower() in ("false", "no"):
                    new = ["true" if other.lower() == "false" else "yes"]
                else:
                    new = []
                blank = [e for e, l in zip(edges, labels) if l == ""]
                if new and len(new) == len(blank):
                    change = Change(
                        id=fid, source=src, title=f"Label the branches of “{node.name}”",
                        rationale="Each outgoing branch needs a label so the result can be matched to a path.",
                        ops=[UpdateEdge(op="update_edge", source=e.source, target=e.target, condition=None, set_condition=lab)
                             for e, lab in zip(blank, new)])

        elif f.rule_id == "condition-input-undeclared":
            # finding sits on the upstream step; the fields come from each condition it feeds
            fields: set[str] = set()
            for e in workflow.edges:
                target = _node(workflow, e.target) if e.source == node.id else None
                if target is not None and target.type == NodeType.CONDITION:
                    expr = target.config.get("expression")
                    fields |= _referenced_fields(expr) if isinstance(expr, str) else set()
            if fields:
                names = sorted(fields)
                change = Change(id=fid, source=src, title=f"Declare {', '.join(names)} in “{node.name}” output",
                                rationale="The next decision reads these fields, so they should be part of this step's declared output.",
                                ops=[UpdateNode(op="update_node", id=node.id, output_schema=_schema_with(node.output_schema, names))])

        elif f.rule_id == "condition-input-missing-field":
            expr = node.config.get("expression")
            fields = _referenced_fields(expr) if isinstance(expr, str) else set()
            ops = []
            for e in workflow.edges:
                pred = _node(workflow, e.source) if e.target == node.id else None
                if pred is None or pred.output_schema is None or pred.type in (NodeType.START, NodeType.CONDITION):
                    continue
                declared = schema_utils.property_names(pred.output_schema)
                missing = sorted(fields - declared) if declared is not None else []
                if missing:
                    ops.append(UpdateNode(op="update_node", id=pred.id, output_schema=_schema_with(pred.output_schema, missing)))
            if ops:
                change = Change(id=fid, source=src, title=f"Declare the fields “{node.name}” reads",
                                rationale="Adds the missing fields to the upstream output schema so the condition can rely on them.", ops=ops)

        elif f.rule_id == "no-failure-branch":
            succ = [e for e in workflow.edges if e.source == node.id]
            if len(succ) == 1 and end is not None:
                cond = _unique(workflow, f"{_slug(node.name)}-ok", taken)
                review = _unique(workflow, f"{_slug(node.name)}-review", taken)
                nxt = succ[0]
                change = Change(
                    id=fid, source=src, title=f"Add a failure branch after “{node.name}”",
                    rationale="If this step fails, a person reviews it instead of the flow stopping.",
                    ops=[
                        UpdateNode(op="update_node", id=node.id, output_schema=_schema_with(node.output_schema, ["ok"])),
                        AddNode(op="add_node", id=cond, type=NodeType.CONDITION, name=f"{node.name} succeeded?", near=node.id,
                                config={"expression": "output.ok"}),
                        AddNode(op="add_node", id=review, type=NodeType.HITL, name=f"Review {node.name} failure", near=cond,
                                config={"instructions": f"“{node.name}” failed. Decide how to proceed."}),
                        RemoveEdge(op="remove_edge", source=node.id, target=nxt.target, condition=nxt.condition),
                        AddEdge(op="add_edge", source=node.id, target=cond),
                        AddEdge(op="add_edge", source=cond, target=nxt.target, condition="true"),
                        AddEdge(op="add_edge", source=cond, target=review, condition="false"),
                        AddEdge(op="add_edge", source=review, target=end.id),
                    ])

        if change is not None and check_applies(workflow, change) is None and all(c.id != change.id for c in changes):
            changes.append(change)
    return changes
