"""Prompt-injection exposure of a workflow (Task 60, Future Directions B8).

Static graph analysis, no AI and no simulation. For each LLM step it asks two questions:

* does untrusted text reach it? (user input, retrieved documents, API responses, database rows, tool output)
* can what it produces reach a step that changes something? (a write API, a write query, a tool)

An LLM step that can be steered by untrusted text and can then trigger an action is exposed. A human review that every
path must pass through between the model and the action ("gated") lowers the severity but is still shown.
"""
from collections import deque

from app.models.workflow import NodeType, Workflow, WorkflowNode
from app.schemas.safety import Exposure, ExposureReport, ExposureSink, ExposureSource
from app.services.linter import _is_irreversible

_SOURCE_KIND = {
    NodeType.START: "user input",
    NodeType.RAG: "retrieved documents",
    NodeType.API: "API response",
    NodeType.DATABASE: "database rows",
    NodeType.TOOL: "tool output",
}

ADVICE = (
    "Put a human review between this step and the action, or have the action take only values the model picks from a "
    "fixed list (not free text), and keep untrusted text out of the instructions this step receives."
)


def _action(node: WorkflowNode) -> str | None:
    """What a step does to the outside world, or None if it only reads."""
    if node.type == NodeType.TOOL:
        return "calls a tool"
    if _is_irreversible(node):
        return "writes to a database" if node.type == NodeType.DATABASE else "writes through an API"
    return None


def _reach(start: str, adjacency: dict[str, list[str]], blocked: set[str] = frozenset()) -> set[str]:
    seen: set[str] = set()
    queue = deque([start])
    while queue:
        for nxt in adjacency.get(queue.popleft(), []):
            if nxt not in seen and nxt not in blocked:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def analyse_exposure(workflow: Workflow) -> ExposureReport:
    nodes = {n.id: n for n in workflow.nodes}
    out: dict[str, list[str]] = {}
    inc: dict[str, list[str]] = {}
    for e in workflow.edges:
        if e.source in nodes and e.target in nodes:
            out.setdefault(e.source, []).append(e.target)
            inc.setdefault(e.target, []).append(e.source)

    hitl = {n.id for n in workflow.nodes if n.type == NodeType.HITL}
    llms = [n for n in workflow.nodes if n.type == NodeType.LLM]
    exposures: list[Exposure] = []

    for llm in llms:
        upstream = _reach(llm.id, inc)
        sources = [
            ExposureSource(node_id=n.id, name=n.name, kind=_SOURCE_KIND[n.type])
            for n in workflow.nodes if n.id in upstream and n.type in _SOURCE_KIND
        ]
        if not sources:
            continue
        downstream = _reach(llm.id, out)
        open_path = _reach(llm.id, out, blocked=hitl)          # reachable without passing a human review
        sinks = [
            ExposureSink(node_id=n.id, name=n.name, action=action, gated=n.id not in open_path)
            for n in workflow.nodes
            if n.id in downstream and (action := _action(n)) is not None
        ]
        if not sinks:
            continue

        ungated = [s for s in sinks if not s.gated]
        severity = "low" if not ungated else "high" if any(s.action != "calls a tool" for s in ungated) else "medium"
        where = ", ".join(f"“{s.name}” ({s.action})" for s in (ungated or sinks)[:4])
        kinds = sorted({s.kind for s in sources})
        message = (
            f"“{llm.name}” reads {', '.join(kinds)} and can lead to {where}"
            + ("" if ungated else ", but a human review stands in between")
            + ". Text planted in that input could steer the model into the action."
        )
        exposures.append(Exposure(node_id=llm.id, name=llm.name, severity=severity, sources=sources, sinks=sinks,
                                  message=message, advice=ADVICE if ungated else "Keep the review in place."))

    order = {"high": 0, "medium": 1, "low": 2}
    exposures.sort(key=lambda x: (order[x.severity], x.name))
    notes = []
    if not llms:
        notes.append("This workflow has no LLM steps, so there is no model for planted text to steer.")
    elif not exposures:
        notes.append("No LLM step both reads untrusted input and can lead to an action.")
    return ExposureReport(exposures=exposures, llm_steps=len(llms), notes=notes)
