"""Deterministic static analysis of a workflow (no LLM, no simulation).

Goes beyond the structural validator: reachability, branching hygiene, failure
handling, ordering of human review vs. irreversible actions, data-flow against
declared data contracts, cycles, and rough per-path cost/latency estimates.

Every finding has a stable ``rule_id``, a severity, an optional ``node_id`` (so the UI
can focus the node) and a ``fix_hint``.
"""
import ast
import re
from collections import defaultdict, deque

from app.models.workflow import NodeType, Workflow, WorkflowNode
from app.schemas.lint import LintFinding, LintResult, LintSeverity, PathEstimate
from app.services import expressions, schema_utils

_MAX_PATHS = 50
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_WRITE_SQL = re.compile(r"^\s*(insert|update|delete|merge|upsert|replace|truncate|drop|alter|create)\b", re.I)
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)[^}]*\}\}")

# Rough heuristics: (latency_ms, cost_usd). Human review is modelled as 5 minutes.
_NODE_ESTIMATES: dict[NodeType, tuple[int, float]] = {
    NodeType.START: (0, 0.0),
    NodeType.END: (0, 0.0),
    NodeType.LLM: (2000, 0.002),
    NodeType.TOOL: (500, 0.0),
    NodeType.API: (400, 0.0),
    NodeType.DATABASE: (100, 0.0),
    NodeType.RAG: (300, 0.0005),
    NodeType.CONDITION: (5, 0.0),
    NodeType.HITL: (300_000, 0.0),
    NodeType.TRANSFORM: (20, 0.0),
}


def lint_workflow(workflow: Workflow) -> LintResult:
    ctx = _Graph(workflow)
    findings: list[LintFinding] = []
    findings += _reachability(ctx)
    findings += _condition_rules(ctx)
    findings += _failure_branches(ctx)
    findings += _hitl_after_irreversible(ctx)
    findings += _data_flow(ctx)
    findings += _cycles(ctx)

    order = {LintSeverity.ERROR: 0, LintSeverity.WARNING: 1, LintSeverity.INFO: 2}
    findings.sort(key=lambda f: (order[f.severity], f.rule_id, f.node_id or ""))
    return LintResult(findings=findings, estimates=_estimate_paths(ctx))


# ── Graph helper ─────────────────────────────────────────────────────────────

class _Graph:
    def __init__(self, workflow: Workflow):
        self.workflow = workflow
        self.nodes: dict[str, WorkflowNode] = {n.id: n for n in workflow.nodes}
        self.out: dict[str, list[str]] = defaultdict(list)
        self.inc: dict[str, list[str]] = defaultdict(list)
        self.out_edges = defaultdict(list)
        for e in workflow.edges:
            if e.source in self.nodes and e.target in self.nodes:
                self.out[e.source].append(e.target)
                self.inc[e.target].append(e.source)
                self.out_edges[e.source].append(e)
        starts = [n for n in workflow.nodes if n.type == NodeType.START]
        self.start = starts[0] if len(starts) == 1 else None
        self.ends = [n for n in workflow.nodes if n.type == NodeType.END]

    def reach(self, seeds: list[str], adjacency: dict[str, list[str]]) -> set[str]:
        seen: set[str] = set()
        queue = deque(seeds)
        while queue:
            current = queue.popleft()
            for nxt in adjacency.get(current, []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    def name(self, node_id: str) -> str:
        return self.nodes[node_id].name


def _finding(rule_id, severity, node_id, message, fix_hint="") -> LintFinding:
    return LintFinding(rule_id=rule_id, severity=severity, node_id=node_id, message=message, fix_hint=fix_hint)


# ── Rules ────────────────────────────────────────────────────────────────────

def _reachability(g: _Graph) -> list[LintFinding]:
    findings: list[LintFinding] = []
    if g.start is None:
        return findings

    reachable = g.reach([g.start.id], g.out) | {g.start.id}
    for node in g.workflow.nodes:
        if node.id not in reachable:
            findings.append(_finding(
                "unreachable-node", LintSeverity.WARNING, node.id,
                f"'{node.name}' cannot be reached from START.",
                "Connect it to the flow, or delete it.",
            ))

    can_finish = set(n.id for n in g.ends) | g.reach([n.id for n in g.ends], g.inc)
    for node in g.workflow.nodes:
        if node.type == NodeType.END or node.id not in reachable or node.id in can_finish:
            continue
        findings.append(_finding(
            "dead-end", LintSeverity.WARNING, node.id,
            f"No path from '{node.name}' leads to an END node.",
            "Add an outgoing edge that eventually reaches END.",
        ))
    return findings


def _condition_rules(g: _Graph) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for node in g.workflow.nodes:
        if node.type != NodeType.CONDITION:
            continue
        edges = g.out_edges.get(node.id, [])
        if len(edges) < 2:
            findings.append(_finding(
                "condition-single-branch", LintSeverity.WARNING, node.id,
                f"Condition '{node.name}' has {len(edges)} outgoing edge(s); a decision needs at least two.",
                "Add a second branch (for example a fallback or 'else' path).",
            ))
        elif any(not (e.condition or "").strip() for e in edges):
            findings.append(_finding(
                "condition-unlabelled-branch", LintSeverity.WARNING, node.id,
                f"Condition '{node.name}' has outgoing edges without a condition label.",
                "Label every branch (true/false, or the values the expression returns).",
            ))
        findings += _condition_input_contract(g, node)
    return findings


def _referenced_fields(expression: str) -> set[str]:
    """Top-level input fields an expression reads (``input.x``, ``output["x"]`` or bare ``x``)."""
    try:
        tree = expressions.parse(expression)
    except expressions.ExpressionError:
        return set()
    fields: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in ("input", "output"):
            fields.add(node.attr)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in ("input", "output")
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            fields.add(node.slice.value)
        elif isinstance(node, ast.Name) and node.id not in ("input", "output", "true", "false", "null"):
            fields.add(node.id)
    return fields


def _condition_input_contract(g: _Graph, node: WorkflowNode) -> list[LintFinding]:
    expression = node.config.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        return []
    fields = _referenced_fields(expression)
    if not fields:
        return []

    findings: list[LintFinding] = []
    for pred_id in g.inc.get(node.id, []):
        pred = g.nodes[pred_id]
        if pred.type in (NodeType.START, NodeType.CONDITION):
            continue
        if pred.output_schema is None:
            if pred.type in (NodeType.LLM, NodeType.API, NodeType.TOOL, NodeType.RAG, NodeType.DATABASE, NodeType.TRANSFORM):
                findings.append(_finding(
                    "condition-input-undeclared", LintSeverity.INFO, pred.id,
                    f"'{pred.name}' feeds condition '{node.name}', which reads {', '.join(sorted(fields))}, "
                    "but declares no output schema.",
                    "Add an output schema so the fields the condition reads are guaranteed to exist.",
                ))
            continue
        declared = schema_utils.property_names(pred.output_schema)
        if declared is None:
            continue
        missing = sorted(fields - declared)
        if missing:
            findings.append(_finding(
                "condition-input-missing-field", LintSeverity.WARNING, node.id,
                f"Condition '{node.name}' reads {', '.join(missing)}, which '{pred.name}' does not declare in its output schema.",
                "Add the field to the upstream output schema, or fix the expression.",
            ))
    return findings


def _failure_branches(g: _Graph) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for node in g.workflow.nodes:
        if node.type not in (NodeType.API, NodeType.DATABASE, NodeType.TOOL):
            continue
        successors = g.out.get(node.id, [])
        if not successors:
            continue  # already reported as dead-end
        handled = len(successors) > 1 or any(g.nodes[s].type == NodeType.CONDITION for s in successors)
        if not handled:
            findings.append(_finding(
                "no-failure-branch", LintSeverity.WARNING, node.id,
                f"'{node.name}' ({node.type.value}) has no failure branch; an error would stop the flow.",
                "Follow it with a CONDITION that routes failures to a fallback or human review.",
            ))
    return findings


def _is_irreversible(node: WorkflowNode) -> bool:
    if node.type == NodeType.API:
        return str(node.config.get("method", "")).upper() in _WRITE_METHODS
    if node.type == NodeType.DATABASE:
        return bool(_WRITE_SQL.match(str(node.config.get("query", ""))))
    return False


# Labels of a branch that is taken when something went wrong. A human review reached only through such a branch is
# handling the failure (for example "the payment did not confirm"), not approving something that has already happened.
_FAILURE_LABELS = {"false", "no", "error", "failed", "failure", "fail", "unsuccessful"}


def _hitl_after_irreversible(g: _Graph) -> list[LintFinding]:
    findings: list[LintFinding] = []
    inc_normal: dict[str, list[str]] = defaultdict(list)       # who leads here, ignoring failure branches
    for e in g.workflow.edges:
        if e.source in g.nodes and e.target in g.nodes and (e.condition or "").strip().lower() not in _FAILURE_LABELS:
            inc_normal[e.target].append(e.source)
    for node in g.workflow.nodes:
        if node.type != NodeType.HITL:
            continue
        ancestors = g.reach([node.id], inc_normal)
        culprits = sorted(g.name(a) for a in ancestors if a != node.id and _is_irreversible(g.nodes[a]))
        if culprits:
            findings.append(_finding(
                "hitl-after-irreversible", LintSeverity.WARNING, node.id,
                f"Human review '{node.name}' comes after irreversible step(s): {', '.join(culprits)}.",
                "Move the approval before the write so a reviewer can stop it.",
            ))
    return findings


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _data_flow(g: _Graph) -> list[LintFinding]:
    """Flag ``{{field}}`` placeholders that no upstream data contract produces."""
    findings: list[LintFinding] = []
    for node in g.workflow.nodes:
        fields = {m.group(1) for s in _strings(node.config) for m in _PLACEHOLDER.finditer(s)}
        if not fields:
            continue
        upstream = g.reach([node.id], g.inc)
        # {{input}} is the workflow input; {{some_node}} refers to an upstream node's whole output.
        produced: set[str] = {"input"}
        for up_id in upstream:
            produced.add(_slug(up_id))
            produced.add(_slug(g.nodes[up_id].name))
        any_contract = False
        for up_id in upstream:
            names = schema_utils.property_names(g.nodes[up_id].output_schema)
            if names is not None:
                any_contract = True
                produced |= names
        if not any_contract:
            continue  # no contracts declared upstream: nothing to check against
        missing = sorted(fields - produced)
        if missing:
            findings.append(_finding(
                "data-flow-missing-field", LintSeverity.WARNING, node.id,
                f"'{node.name}' uses {', '.join('{{' + m + '}}' for m in missing)}, which no upstream node produces.",
                "Declare the field in an upstream output schema, or correct the placeholder.",
            ))
    return findings


def _cycles(g: _Graph) -> list[LintFinding]:
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {nid: WHITE for nid in g.nodes}
    reported: set[str] = set()
    findings: list[LintFinding] = []

    def visit(nid: str, stack: list[str]) -> None:
        colour[nid] = GREY
        stack.append(nid)
        for nxt in g.out.get(nid, []):
            if colour[nxt] == GREY:
                cycle = stack[stack.index(nxt):]
                key = ",".join(sorted(cycle))
                if key not in reported:
                    reported.add(key)
                    names = " → ".join(g.name(c) for c in cycle + [nxt])
                    findings.append(_finding(
                        "cycle", LintSeverity.WARNING, nxt,
                        f"Cycle detected: {names}. Simulation requires an acyclic workflow.",
                        "For a retry/reflection loop, use a bounded pattern: a counter in the data and a "
                        "CONDITION that exits after N attempts (loops are not simulated yet).",
                    ))
            elif colour[nxt] == WHITE:
                visit(nxt, stack)
        stack.pop()
        colour[nid] = BLACK

    for nid in list(g.nodes):
        if colour[nid] == WHITE:
            visit(nid, [])
    return findings


# ── Estimates ────────────────────────────────────────────────────────────────

def _estimate_paths(g: _Graph) -> list[PathEstimate]:
    if g.start is None or not g.ends:
        return []
    end_ids = {n.id for n in g.ends}
    estimates: list[PathEstimate] = []

    def walk(nid: str, path: list[str]) -> None:
        if len(estimates) >= _MAX_PATHS:
            return
        path = path + [nid]
        if nid in end_ids:
            latency = sum(_NODE_ESTIMATES.get(g.nodes[p].type, (0, 0.0))[0] for p in path)
            cost = sum(_NODE_ESTIMATES.get(g.nodes[p].type, (0, 0.0))[1] for p in path)
            estimates.append(PathEstimate(
                node_ids=path,
                node_names=[g.name(p) for p in path],
                latency_ms=latency,
                cost_usd=round(cost, 6),
            ))
            return
        for nxt in g.out.get(nid, []):
            if nxt not in path:
                walk(nxt, path)

    walk(g.start.id, [])
    return estimates
