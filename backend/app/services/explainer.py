"""Plain-language Markdown description of a workflow (no LLM, deterministic).

Written for the people who approve or maintain a workflow rather than the person who built it:
what it does step by step, where humans are involved, what it connects to, and what the automatic
checks found. The same workflow always produces the same text, so it is safe to diff and to cache.
"""
import heapq
import re
from collections import deque
from typing import Any

from app.models.workflow import NodeType, Workflow, WorkflowNode
from app.schemas.lint import LintSeverity
from app.services import schema_utils
from app.services.linter import _is_irreversible, lint_workflow

_MAX_TEXT = 140

_KIND_WORDS = {
    NodeType.LLM: "AI model call",
    NodeType.TOOL: "tool",
    NodeType.API: "external service call",
    NodeType.DATABASE: "database query",
    NodeType.RAG: "knowledge search",
    NodeType.CONDITION: "decision",
    NodeType.HITL: "human review",
    NodeType.TRANSFORM: "data step",
}


# ── Small formatting helpers ─────────────────────────────────────────────────

def _oneline(text: Any, limit: int = _MAX_TEXT) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _code(text: Any, limit: int = _MAX_TEXT) -> str:
    """Inline code that cannot break out of its backticks."""
    return f"`{_oneline(text, limit).replace('`', chr(39))}`"


def _cell(text: Any, limit: int = 80) -> str:
    """Table cell text: no pipes, backticks or line breaks."""
    return _oneline(text, limit).replace("|", "\\|").replace("`", "'")


def _bold(name: str) -> str:
    return f"**{_oneline(name, 60).replace('*', '')}**"


def _duration(ms: int) -> str:
    if ms < 1000:
        return f"{ms} ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{round(seconds, 1):g} s"
    minutes = seconds / 60
    return f"{minutes:.0f} min" if minutes >= 10 else f"{round(minutes, 1):g} min"


def _cost(usd: float) -> str:
    if usd == 0:
        return "$0"
    return f"${usd:.4f}" if usd < 0.01 else f"${usd:.2f}"


def _range(low: float, high: float, fmt) -> str:
    return fmt(low) if low == high else f"{fmt(low)} – {fmt(high)}"


# ── Per-node descriptions ────────────────────────────────────────────────────

def _produces(node: WorkflowNode) -> str:
    props = schema_utils.property_names(node.output_schema)
    if not props:
        return ""
    declared = node.output_schema["properties"]
    parts = []
    for name in sorted(props):
        kind = (declared[name] or {}).get("type") if isinstance(declared[name], dict) else None
        parts.append(f"`{name}`" + (f" ({kind})" if kind else ""))
    return "Produces " + ", ".join(parts) + "."


def _what(node: WorkflowNode) -> str:
    cfg = node.config
    t = node.type
    if t == NodeType.START:
        return "the workflow begins here."
    if t == NodeType.END:
        return "the workflow finishes here."
    if t == NodeType.LLM:
        model = f" ({_oneline(cfg.get('model'), 40)})" if cfg.get("model") else ""
        prompt = f" Instruction: “{_oneline(cfg['prompt'])}”" if cfg.get("prompt") else ""
        return f"asks an AI model{model}.{prompt}"
    if t == NodeType.TOOL:
        label = _code(cfg.get("name") or node.name, 60)
        extra = f" — {_oneline(cfg['description'])}" if cfg.get("description") else ""
        return f"runs the tool {label}{extra}."
    if t == NodeType.API:
        method = str(cfg.get("method") or "").upper() or "a request"
        target = _code(cfg.get("url") or "(no address set)", 100)
        effect = "changes data in another system" if _is_irreversible(node) else "reads from another system"
        return f"calls an external service: {method} {target} — {effect}."
    if t == NodeType.DATABASE:
        effect = "changes stored data" if _is_irreversible(node) else "reads stored data"
        query = f" Query: {_code(cfg['query'], 100)}" if cfg.get("query") else ""
        return f"runs a database query that {effect}.{query}"
    if t == NodeType.RAG:
        kb = _code(cfg.get("knowledgeBase") or "(no knowledge base set)", 60)
        top = f", keeping the top {cfg['topK']} matches" if cfg.get("topK") else ""
        return f"searches the knowledge base {kb}{top}."
    if t == NodeType.CONDITION:
        expr = cfg.get("expression")
        return f"makes a decision{f' using {_code(expr, 100)}' if expr else ' (no rule set yet)'}."
    if t == NodeType.HITL:
        instr = f" Instructions: “{_oneline(cfg['instructions'])}”" if cfg.get("instructions") else ""
        return f"pauses until a person reviews it.{instr}"
    if t == NodeType.TRANSFORM:
        return f"reshapes the data{f': {_oneline(cfg['description'])}' if cfg.get('description') else ''}."
    return "runs."


def _order(workflow: Workflow) -> tuple[list[WorkflowNode], list[WorkflowNode]]:
    """(nodes reachable from START in walk order, nodes not connected to it)."""
    by_id = {n.id: n for n in workflow.nodes}
    out: dict[str, list[str]] = {}
    for e in workflow.edges:
        if e.source in by_id and e.target in by_id:
            out.setdefault(e.source, []).append(e.target)
    starts = [n for n in workflow.nodes if n.type == NodeType.START]
    seen: list[str] = []
    if len(starts) == 1:
        queue = deque([starts[0].id])
        marked = {starts[0].id}
        while queue:
            current = queue.popleft()
            seen.append(current)
            for nxt in out.get(current, []):
                if nxt not in marked:
                    marked.add(nxt)
                    queue.append(nxt)
    # Read in flow order: a step comes after everything that leads into it (Kahn's algorithm), with
    # ties broken by distance from the start. Steps caught in a cycle are appended in walk order.
    position = {node_id: i for i, node_id in enumerate(seen)}
    members = set(seen)
    incoming = {node_id: 0 for node_id in seen}
    for source in seen:
        for target in out.get(source, []):
            if target in members:
                incoming[target] += 1
    heap = [(position[i], i) for i in seen if incoming[i] == 0]
    heapq.heapify(heap)
    ordered: list[str] = []
    while heap:
        _, current = heapq.heappop(heap)
        ordered.append(current)
        for target in out.get(current, []):
            if target in members:
                incoming[target] -= 1
                if incoming[target] == 0:
                    heapq.heappush(heap, (position[target], target))
    ordered += [i for i in seen if i not in set(ordered)]
    reachable = [by_id[i] for i in ordered]
    rest = [n for n in workflow.nodes if n.id not in members]
    return reachable, rest


# ── Document ─────────────────────────────────────────────────────────────────

def explain_workflow(workflow: Workflow) -> str:
    lint = lint_workflow(workflow)
    nodes = workflow.nodes
    by_id = {n.id: n for n in nodes}
    count = {t: sum(1 for n in nodes if n.type == t) for t in NodeType}
    external = [n for n in nodes if n.type in (NodeType.API, NodeType.DATABASE, NodeType.TOOL, NodeType.RAG)]
    steps = len([n for n in nodes if n.type not in (NodeType.START, NodeType.END)])

    lines: list[str] = [f"# {_oneline(workflow.name, 100)}", ""]
    if workflow.description.strip():
        lines += [_oneline(workflow.description, 400), ""]

    if not nodes:
        return "\n".join(lines + ["_This workflow has no steps yet._", ""])

    parts = [f"{steps} step{'s' if steps != 1 else ''}"]
    if count[NodeType.LLM]:
        parts.append(f"{count[NodeType.LLM]} AI model call{'s' if count[NodeType.LLM] != 1 else ''}")
    if count[NodeType.CONDITION]:
        parts.append(f"{count[NodeType.CONDITION]} decision{'s' if count[NodeType.CONDITION] != 1 else ''}")
    if count[NodeType.HITL]:
        parts.append(f"{count[NodeType.HITL]} human review{'s' if count[NodeType.HITL] != 1 else ''}")
    if external:
        parts.append(f"{len(external)} external connection{'s' if len(external) != 1 else ''}")
    lines += [f"In short: {', '.join(parts)}.", ""]

    # ── At a glance
    lines += ["## At a glance", "", "| | |", "|---|---|"]
    lines.append(f"| Steps | {steps} |")
    lines.append(f"| AI model calls | {count[NodeType.LLM]} |")
    lines.append(f"| Decisions | {count[NodeType.CONDITION]} |")
    lines.append(f"| Human reviews | {count[NodeType.HITL]} |")
    lines.append(f"| External connections | {len(external)} |")
    if lint.estimates:
        n_paths = len(lint.estimates)
        lines.append(f"| Possible routes | {n_paths if n_paths < 50 else '50+'} |")
        lat = [e.latency_ms for e in lint.estimates]
        cost = [e.cost_usd for e in lint.estimates]
        lines.append(f"| Rough time per run | {_range(min(lat), max(lat), _duration)} (a human review is counted as 5 min) |")
        lines.append(f"| Rough AI cost per run | {_range(min(cost), max(cost), _cost)} |")
    lines.append("")

    # ── How it works
    reachable, unreachable = _order(workflow)
    sample = workflow.metadata.get("sample_input") if isinstance(workflow.metadata, dict) else None
    lines += ["## How it works", ""]
    if isinstance(sample, dict) and sample:
        lines += [f"It expects input such as: {', '.join(f'`{k}`' for k in list(sample)[:8])}.", ""]
    out_edges: dict[str, list] = {}
    for e in workflow.edges:
        if e.source in by_id and e.target in by_id:
            out_edges.setdefault(e.source, []).append(e)

    for i, node in enumerate(reachable, 1):
        lines.append(f"{i}. {_bold(node.name)} — {_what(node)}")
        produced = _produces(node)
        if produced:
            lines.append(f"   - {produced}")
        edges = out_edges.get(node.id, [])
        if node.type == NodeType.CONDITION:
            for e in edges:
                label = f"if {_bold(e.condition)}" if (e.condition or "").strip() else "otherwise"
                lines.append(f"   - {label}: go to {_bold(by_id[e.target].name)}")
            if not edges:
                lines.append("   - (no branches are connected)")
        elif node.type != NodeType.END:
            if not edges:
                lines.append("   - Then: nothing is connected after this step.")
            elif len(edges) == 1:
                lines.append(f"   - Then: {_bold(by_id[edges[0].target].name)}")
            else:
                names = " and ".join(_bold(by_id[e.target].name) for e in edges)
                lines.append(f"   - Then, in parallel: {names}")
    if unreachable:
        lines += ["", "**Not connected to the start** (these never run): " + ", ".join(_bold(n.name) for n in unreachable) + ".", ""]
    else:
        lines.append("")

    # ── People
    lines += ["## People in the loop", ""]
    reviews = [n for n in nodes if n.type == NodeType.HITL]
    if reviews:
        for n in reviews:
            instr = f" — “{_oneline(n.config['instructions'])}”" if n.config.get("instructions") else ""
            lines.append(f"- {_bold(n.name)}{instr}")
    else:
        lines.append("Nobody reviews anything: this workflow runs without human approval.")
    lines.append("")

    # ── Connections
    lines += ["## What it connects to", ""]
    if external:
        lines += ["| Step | Kind | Target | Effect |", "|---|---|---|---|"]
        for n in external:
            kind = _KIND_WORDS[n.type]
            if n.type == NodeType.API:
                target = f"{str(n.config.get('method') or '').upper()} {n.config.get('url') or ''}".strip()
                effect = "writes" if _is_irreversible(n) else "reads"
            elif n.type == NodeType.DATABASE:
                target = n.config.get("query") or ""
                effect = "writes" if _is_irreversible(n) else "reads"
            elif n.type == NodeType.RAG:
                target, effect = n.config.get("knowledgeBase") or "", "reads"
            else:
                target, effect = n.config.get("name") or n.name, "unknown"
            lines.append(f"| {_cell(n.name, 40)} | {kind} | {_cell(target or '—')} | {effect} |")
    else:
        lines.append("Nothing outside the workflow itself.")
    lines.append("")

    # ── Things to check
    lines += ["## Things to check", ""]
    findings = [f for f in lint.findings if f.severity != LintSeverity.INFO]
    if findings:
        for f in findings:
            hint = f" *Suggestion:* {f.fix_hint}" if f.fix_hint else ""
            lines.append(f"- {f.message}{hint}")
    else:
        lines.append("The automatic checks found no problems.")
    lines += [
        "",
        "---",
        "_This describes the workflow as designed, not a run. Time and cost figures are rough estimates from fixed per-step assumptions._",
        "",
    ]
    return "\n".join(lines)
