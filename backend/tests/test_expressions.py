"""Tests for the safe CONDITION expression evaluator, routing contract, and validator checks."""
import pytest

from app.models.workflow import NodeType, Workflow, WorkflowEdge, WorkflowNode
from app.schemas.simulation import ConditionMode, SimulationSettings
from app.services import expressions as ex
from app.services.node_handlers import select_condition_edges
from app.services.validator import validate_workflow


# ── Evaluator: supported language ────────────────────────────────────────────

@pytest.mark.parametrize("expr,ctx,expected", [
    ("x > 5", {"x": 10}, True),
    ("x > 5 and y == 'a'", {"x": 10, "y": "a"}, True),
    ("not flag", {"flag": False}, True),
    ("input.status == 'open'", {"input": {"status": "open"}}, True),
    ("output['n'] + 1", {"output": {"n": 2}}, 3),
    ("items[0] == 1", {"items": [1, 2]}, True),
    ("x in ['a', 'b']", {"x": "b"}, True),
    ("1 < x <= 3", {"x": 3}, True),
    ("'big' if x > 100 else 'small'", {"x": 3}, "small"),
    ("true and not false", {}, True),
    ("x == null", {"x": None}, True),
    ("x * 2", {"x": 2.5}, 5.0),
])
def test_supported_expressions(expr, ctx, expected):
    assert ex.evaluate(expr, ctx) == expected


# ── Evaluator: escape attempts and abuse ─────────────────────────────────────

@pytest.mark.parametrize("expr", [
    "().__class__.__mro__[1].__subclasses__()",
    "x.__class__",
    "x.__dict__",
    "__import__('os').system('echo pwned')",
    "open('/etc/passwd')",
    "eval('1')",
    "exec('1')",
    "(lambda: 1)()",
    "[c for c in ().__class__.__bases__]",
    "{k: 1 for k in x}",
    "f'{x}'",
    "x[1:2]",
    "x is None",
    "2 ** 10",
    "(y := 1)",
    "await x",
    "'a' * 10 ** 9",
    "_private",
    "input._secret",
    "input['_secret']",
    "x.__init__.__globals__",
    "import os",
    "1; 2",
])
def test_escape_attempts_are_rejected(expr):
    with pytest.raises(ex.ExpressionError):
        ex.evaluate(expr, {"x": [1], "input": {"_secret": 1}, "_private": 1})


def test_huge_expression_rejected():
    with pytest.raises(ex.ExpressionError):
        ex.evaluate("1 + " * 400 + "1", {})
    with pytest.raises(ex.ExpressionError):
        ex.evaluate("(" * 5000 + "1" + ")" * 5000, {})


def test_too_many_nodes_rejected():
    with pytest.raises(ex.ExpressionError):
        ex.evaluate(" + ".join(["1"] * 80), {})


def test_sequence_repeat_bomb_rejected():
    with pytest.raises(ex.ExpressionError):
        ex.evaluate("'abc' * 100000", {})


@pytest.mark.parametrize("expr,ctx", [
    ("missing > 1", {}),
    ("input.nope", {"input": {}}),
    ("items[5]", {"items": [1]}),
    ("x > 1", {"x": None}),          # None > 1 -> TypeError
    ("1 / 0", {}),
    ("", {}),
    ("x ==", {"x": 1}),
])
def test_evaluation_failures_raise_expression_error(expr, ctx):
    with pytest.raises(ex.ExpressionError):
        ex.evaluate(expr, ctx)


def test_check_syntax():
    assert ex.check_syntax("x > 1") is None
    assert ex.check_syntax("x > 1 && y") is not None   # JS-style operator
    assert ex.check_syntax("f(x)") is not None


def test_possible_results():
    assert ex.possible_results("x > 1") == {True, False}
    assert ex.possible_results("'a' if x else 'b'") == {"a", "b"}
    assert ex.possible_results("x") is None


# ── Routing contract ─────────────────────────────────────────────────────────

def _cond(expression, labels):
    node = WorkflowNode(id="c", type=NodeType.CONDITION, name="Router", config={"expression": expression})
    edges = [WorkflowEdge(source="c", target=f"t{i}", condition=l) for i, l in enumerate(labels)]
    return node, edges


def _settings():
    return SimulationSettings(condition_mode=ConditionMode.EXPRESSION)


def test_boolean_result_routes_to_true_false_labels():
    node, edges = _cond("x > 1", ["true", "false"])
    chosen, warnings = select_condition_edges(node, edges, {"x": 5}, _settings())
    assert [e.target for e in chosen] == ["t0"] and warnings == []
    chosen, _ = select_condition_edges(node, edges, {"x": 0}, _settings())
    assert [e.target for e in chosen] == ["t1"]


def test_yes_no_labels_and_case_insensitive():
    node, edges = _cond("x > 1", ["No", "YES"])
    chosen, _ = select_condition_edges(node, edges, {"x": 5}, _settings())
    assert [e.target for e in chosen] == ["t1"]


def test_string_result_routes_to_matching_label():
    node, edges = _cond("'premium' if input.tier == 'gold' else 'basic'", ["basic", "premium"])
    chosen, warnings = select_condition_edges(node, edges, {"tier": "gold"}, _settings())
    assert [e.target for e in chosen] == ["t1"] and warnings == []


def test_default_label_is_fallback():
    node, edges = _cond("kind", ["a", "else"])
    chosen, warnings = select_condition_edges(node, edges, {"kind": "zzz"}, _settings())
    assert [e.target for e in chosen] == ["t1"] and warnings == []


def test_unmatched_result_follows_all_edges_with_warning():
    node, edges = _cond("x > 1", ["positive", "negative"])
    chosen, warnings = select_condition_edges(node, edges, {"x": 5}, _settings())
    assert len(chosen) == 2
    assert warnings and "matches no edge label" in warnings[0]


def test_evaluation_error_is_reported_not_silent():
    node, edges = _cond("missing_field > 1", ["true", "false"])
    chosen, warnings = select_condition_edges(node, edges, {}, _settings())
    assert len(chosen) == 2
    assert warnings and "missing_field" in warnings[0]


def test_hostile_expression_is_reported_and_not_executed():
    node, edges = _cond("().__class__.__mro__", ["true", "false"])
    chosen, warnings = select_condition_edges(node, edges, {}, _settings())
    assert len(chosen) == 2 and warnings


def test_missing_expression_warns():
    node, edges = _cond("", ["true", "false"])
    _, warnings = select_condition_edges(node, edges, {}, _settings())
    assert warnings


# ── Trace integration ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trace_step_carries_routing_warning():
    from app.services.simulator import simulate
    wf = Workflow(
        name="W",
        nodes=[
            WorkflowNode(id="s", type=NodeType.START, name="Start"),
            WorkflowNode(id="c", type=NodeType.CONDITION, name="C", config={"expression": "nope > 1"}),
            WorkflowNode(id="a", type=NodeType.END, name="A"),
            WorkflowNode(id="b", type=NodeType.END, name="B"),
        ],
        edges=[
            WorkflowEdge(source="s", target="c"),
            WorkflowEdge(source="c", target="a", condition="true"),
            WorkflowEdge(source="c", target="b", condition="false"),
        ],
    )
    trace = await simulate(wf, {}, _settings())
    cond_step = next(s for s in trace.steps if s.node_id == "c")
    assert cond_step.warnings and "nope" in cond_step.warnings[0]


# ── Validator contract checks ────────────────────────────────────────────────

def _wf(expression, labels):
    node, edges = _cond(expression, labels)
    nodes = [WorkflowNode(id="s", type=NodeType.START, name="Start"), node] + [
        WorkflowNode(id=f"t{i}", type=NodeType.END, name=f"End{i}") for i in range(len(labels))
    ]
    return Workflow(nodes=nodes, edges=[WorkflowEdge(source="s", target="c")] + edges)


def test_validator_accepts_matching_labels():
    r = validate_workflow(_wf("x > 1", ["true", "false"]))
    assert not [w for w in r.warnings if "Condition" in w]


def test_validator_accepts_label_returning_expression():
    r = validate_workflow(_wf("'a' if x else 'b'", ["a", "b"]))
    assert not [w for w in r.warnings if "Condition" in w]


def test_validator_warns_unmatchable_labels():
    r = validate_workflow(_wf("x > 1", ["positive", "negative"]))
    text = " ".join(r.warnings)
    assert "can never be selected" in text and "no outgoing edge" in text


def test_validator_warns_unlabelled_edges_and_bad_syntax():
    r = validate_workflow(_wf("x > 1", [None, "true"]))
    assert any("without a condition label" in w for w in r.warnings)
    r = validate_workflow(_wf("x > 1 && y", ["true", "false"]))
    assert any("invalid expression" in w for w in r.warnings)
