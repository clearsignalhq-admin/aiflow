"""Tests for the static-analysis lint engine and the /workflows/lint endpoint."""
import glob
import json
import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.workflow import NodeType, Workflow, WorkflowEdge, WorkflowNode
from app.schemas.lint import LintSeverity
from app.services.linter import lint_workflow

BASE = "http://test"
EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "examples")


def N(id, type, name=None, **kw):
    return WorkflowNode(id=id, type=type, name=name or id, **kw)


def E(source, target, condition=None):
    return WorkflowEdge(source=source, target=target, condition=condition)


def rules(wf: Workflow) -> set[str]:
    return {f.rule_id for f in lint_workflow(wf).findings}


def findings(wf: Workflow, rule: str):
    return [f for f in lint_workflow(wf).findings if f.rule_id == rule]


def linear():
    return Workflow(
        nodes=[N("s", NodeType.START), N("t", NodeType.TRANSFORM), N("e", NodeType.END)],
        edges=[E("s", "t"), E("t", "e")],
    )


def test_clean_linear_workflow_has_no_findings():
    assert lint_workflow(linear()).findings == []


def test_unreachable_node():
    wf = linear()
    wf.nodes.append(N("x", NodeType.TRANSFORM, "Orphan"))
    [f] = findings(wf, "unreachable-node")
    assert f.node_id == "x" and f.fix_hint and f.severity == LintSeverity.WARNING


def test_dead_end_node():
    wf = Workflow(
        nodes=[N("s", NodeType.START), N("a", NodeType.TRANSFORM, "A"), N("e", NodeType.END)],
        edges=[E("s", "a")],
    )
    assert "a" in {f.node_id for f in findings(wf, "dead-end")}


def test_condition_single_branch_and_unlabelled():
    one = Workflow(
        nodes=[N("s", NodeType.START), N("c", NodeType.CONDITION, config={"expression": "x"}), N("e", NodeType.END)],
        edges=[E("s", "c"), E("c", "e", "true")],
    )
    assert "condition-single-branch" in rules(one)

    unlabelled = Workflow(
        nodes=[N("s", NodeType.START), N("c", NodeType.CONDITION, config={"expression": "x"}),
               N("a", NodeType.END, "A"), N("b", NodeType.END, "B")],
        edges=[E("s", "c"), E("c", "a", "true"), E("c", "b")],
    )
    assert "condition-unlabelled-branch" in rules(unlabelled)


def test_no_failure_branch_and_handled_variants():
    bare = Workflow(
        nodes=[N("s", NodeType.START), N("a", NodeType.API, config={"method": "GET", "url": "u"}), N("e", NodeType.END)],
        edges=[E("s", "a"), E("a", "e")],
    )
    assert [f.node_id for f in findings(bare, "no-failure-branch")] == ["a"]

    handled = Workflow(
        nodes=[N("s", NodeType.START), N("a", NodeType.API, config={"method": "GET", "url": "u"}),
               N("c", NodeType.CONDITION, config={"expression": "x"}), N("e", NodeType.END), N("f", NodeType.END, "Fail")],
        edges=[E("s", "a"), E("a", "c"), E("c", "e", "true"), E("c", "f", "false")],
    )
    assert "no-failure-branch" not in rules(handled)


@pytest.mark.parametrize("node,expected", [
    (N("w", NodeType.API, config={"method": "POST", "url": "u"}), True),
    (N("w", NodeType.API, config={"method": "GET", "url": "u"}), False),
    (N("w", NodeType.DATABASE, config={"query": "INSERT INTO t VALUES (1)"}), True),
    (N("w", NodeType.DATABASE, config={"query": "SELECT * FROM t"}), False),
])
def test_hitl_after_irreversible(node, expected):
    wf = Workflow(
        nodes=[N("s", NodeType.START), node, N("h", NodeType.HITL, config={"instructions": "ok?"}), N("e", NodeType.END)],
        edges=[E("s", "w"), E("w", "h"), E("h", "e")],
    )
    assert ("hitl-after-irreversible" in rules(wf)) is expected


def test_hitl_before_write_is_fine():
    wf = Workflow(
        nodes=[N("s", NodeType.START), N("h", NodeType.HITL), N("w", NodeType.DATABASE, config={"query": "DELETE FROM t"}),
               N("e", NodeType.END)],
        edges=[E("s", "h"), E("h", "w"), E("w", "e")],
    )
    assert "hitl-after-irreversible" not in rules(wf)


def _cond_wf(llm_schema, expression="input.tier == 'gold'"):
    return Workflow(
        nodes=[
            N("s", NodeType.START),
            N("l", NodeType.LLM, "Classify", output_schema=llm_schema),
            N("c", NodeType.CONDITION, "Route", config={"expression": expression}),
            N("a", NodeType.END, "A"), N("b", NodeType.END, "B"),
        ],
        edges=[E("s", "l"), E("l", "c"), E("c", "a", "true"), E("c", "b", "false")],
    )


def test_condition_reads_undeclared_output():
    [f] = findings(_cond_wf(None), "condition-input-undeclared")
    assert f.node_id == "l" and f.severity == LintSeverity.INFO


def test_condition_reads_field_missing_from_contract():
    wf = _cond_wf({"type": "object", "properties": {"other": {"type": "string"}}})
    [f] = findings(wf, "condition-input-missing-field")
    assert f.node_id == "c" and "tier" in f.message


def test_condition_with_declared_field_is_clean():
    wf = _cond_wf({"type": "object", "properties": {"tier": {"type": "string"}}})
    assert not {"condition-input-undeclared", "condition-input-missing-field"} & rules(wf)


def test_data_flow_missing_placeholder_field():
    wf = Workflow(
        nodes=[
            N("s", NodeType.START),
            N("a", NodeType.API, config={"method": "GET", "url": "u"}, output_schema={"type": "object", "properties": {"order_id": {"type": "string"}}}),
            N("l", NodeType.LLM, config={"prompt": "Order {{order_id}} for {{customer_name}}"}),
            N("e", NodeType.END),
        ],
        edges=[E("s", "a"), E("a", "l"), E("l", "e")],
    )
    [f] = findings(wf, "data-flow-missing-field")
    assert f.node_id == "l" and "customer_name" in f.message and "order_id" not in f.message


def test_data_flow_skipped_without_any_contract():
    wf = Workflow(
        nodes=[N("s", NodeType.START), N("l", NodeType.LLM, config={"prompt": "Hi {{name}}"}), N("e", NodeType.END)],
        edges=[E("s", "l"), E("l", "e")],
    )
    assert "data-flow-missing-field" not in rules(wf)


def test_cycle_detected_with_bounded_loop_hint():
    wf = Workflow(
        nodes=[N("s", NodeType.START), N("a", NodeType.TRANSFORM, "A"), N("b", NodeType.TRANSFORM, "B"), N("e", NodeType.END)],
        edges=[E("s", "a"), E("a", "b"), E("b", "a"), E("b", "e")],
    )
    [f] = findings(wf, "cycle")
    assert "A" in f.message and "B" in f.message and "bounded" in f.fix_hint


def test_estimates_per_path():
    wf = Workflow(
        nodes=[
            N("s", NodeType.START), N("l", NodeType.LLM),
            N("c", NodeType.CONDITION, config={"expression": "x"}),
            N("h", NodeType.HITL), N("a", NodeType.END, "A"), N("b", NodeType.END, "B"),
        ],
        edges=[E("s", "l"), E("l", "c"), E("c", "h", "true"), E("h", "a"), E("c", "b", "false")],
    )
    est = lint_workflow(wf).estimates
    assert len(est) == 2
    by_end = {e.node_ids[-1]: e for e in est}
    assert by_end["b"].latency_ms == 2005 and by_end["b"].cost_usd == 0.002
    assert by_end["a"].latency_ms == 2005 + 300_000


def test_estimates_capped_for_wide_graphs():
    # 7 sequential 2-way diamonds -> 128 paths; must be capped.
    nodes, edges, prev = [N("s", NodeType.START)], [], "s"
    for i in range(7):
        a, b, j = f"a{i}", f"b{i}", f"j{i}"
        nodes += [N(a, NodeType.TRANSFORM), N(b, NodeType.TRANSFORM), N(j, NodeType.TRANSFORM)]
        edges += [E(prev, a), E(prev, b), E(a, j), E(b, j)]
        prev = j
    nodes.append(N("e", NodeType.END))
    edges.append(E(prev, "e"))
    assert len(lint_workflow(Workflow(nodes=nodes, edges=edges)).estimates) <= 50


def test_findings_sorted_and_workflow_without_start_does_not_crash():
    wf = Workflow(nodes=[N("a", NodeType.TRANSFORM)], edges=[])
    assert lint_workflow(wf).findings == []


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(EXAMPLES, "**", "*.json"), recursive=True)))
def test_examples_have_no_lint_warnings_for_contract_or_cycles(path):
    wf = Workflow(**json.load(open(path, encoding="utf-8")))
    bad = {f.rule_id for f in lint_workflow(wf).findings} & {
        "cycle", "unreachable-node", "dead-end", "condition-input-missing-field", "data-flow-missing-field",
    }
    assert not bad


@pytest.mark.asyncio
@pytest.mark.usefixtures("override_approved_user")
async def test_lint_endpoint():
    wf = linear().model_dump(mode="json")
    wf["nodes"].append({"id": "x", "type": "TRANSFORM", "name": "Orphan"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/lint", json={"workflow": wf})
    assert res.status_code == 200
    body = res.json()
    assert any(f["rule_id"] == "unreachable-node" and f["node_id"] == "x" for f in body["findings"])
    assert body["estimates"][0]["node_ids"] == ["s", "t", "e"]


@pytest.mark.asyncio
async def test_lint_endpoint_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        res = await client.post("/api/workflows/lint", json={"workflow": linear().model_dump(mode="json")})
    assert res.status_code in (401, 403)
