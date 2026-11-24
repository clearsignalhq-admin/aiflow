from app.models.workflow import Workflow, NodeType
from app.schemas.requests import ValidationResult
from app.services import expressions

# Required config keys per node type
_REQUIRED_CONFIG: dict[NodeType, list[str]] = {
    NodeType.LLM: ["prompt"],
    NodeType.API: ["method", "url"],
    NodeType.DATABASE: ["query"],
    NodeType.RAG: ["knowledgeBase"],
    NodeType.CONDITION: ["expression"],
    NodeType.HITL: ["instructions"],
}


def validate_workflow(workflow: Workflow) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    node_ids = [n.id for n in workflow.nodes]

    # Duplicate IDs
    seen: set[str] = set()
    for nid in node_ids:
        if nid in seen:
            errors.append(f"Duplicate node ID: '{nid}'")
        seen.add(nid)

    # START / END counts
    start_nodes = [n for n in workflow.nodes if n.type == NodeType.START]
    end_nodes = [n for n in workflow.nodes if n.type == NodeType.END]

    if len(start_nodes) == 0:
        errors.append("Workflow must have exactly one START node.")
    elif len(start_nodes) > 1:
        errors.append(f"Workflow has {len(start_nodes)} START nodes; exactly one is required.")

    if len(end_nodes) == 0:
        errors.append("Workflow must have at least one END node.")

    # Edge references
    id_set = set(node_ids)
    for edge in workflow.edges:
        if edge.source not in id_set:
            errors.append(f"Edge references unknown source node: '{edge.source}'")
        if edge.target not in id_set:
            errors.append(f"Edge references unknown target node: '{edge.target}'")

    # Required config
    for node in workflow.nodes:
        required = _REQUIRED_CONFIG.get(node.type, [])
        for key in required:
            if key not in node.config or not node.config[key]:
                warnings.append(
                    f"Node '{node.name}' ({node.type}) is missing recommended config field: '{key}'"
                )

    # Disconnected nodes (warn only)
    connected_ids: set[str] = set()
    for edge in workflow.edges:
        connected_ids.add(edge.source)
        connected_ids.add(edge.target)

    for node in workflow.nodes:
        if node.type not in (NodeType.START, NodeType.END) and node.id not in connected_ids:
            warnings.append(f"Node '{node.name}' ({node.id}) is not connected to any edge.")

    warnings.extend(_condition_warnings(workflow))

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def _condition_warnings(workflow: Workflow) -> list[str]:
    """Check each CONDITION node's expression and edge labels against the routing contract."""
    warnings: list[str] = []
    for node in workflow.nodes:
        if node.type != NodeType.CONDITION:
            continue
        outgoing = [e for e in workflow.edges if e.source == node.id]
        label = f"Condition '{node.name}'"

        unlabelled = [e for e in outgoing if not (e.condition or "").strip()]
        if unlabelled:
            warnings.append(f"{label} has {len(unlabelled)} outgoing edge(s) without a condition label.")

        expression = node.config.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            continue  # already reported as missing config

        problem = expressions.check_syntax(expression)
        if problem:
            warnings.append(f"{label} has an invalid expression: {problem}")
            continue

        results = expressions.possible_results(expression)
        if results is None:
            continue  # result values unknown statically
        edge_labels = {expressions.normalise_label(e.condition) for e in outgoing if (e.condition or "").strip()}
        if not edge_labels:
            continue
        has_default = bool(edge_labels & expressions.DEFAULT_LABELS)

        produced: set[str] = set()
        for value in results:
            candidates = expressions.label_candidates(value)
            produced |= candidates
            if not (candidates & edge_labels) and not has_default:
                warnings.append(
                    f"{label}: expression can return {value!r} but no outgoing edge is labelled "
                    f"{' / '.join(sorted(candidates))}."
                )
        for edge_label in sorted(edge_labels - produced - expressions.DEFAULT_LABELS):
            warnings.append(f"{label}: edge label '{edge_label}' can never be selected by the expression.")
    return warnings
