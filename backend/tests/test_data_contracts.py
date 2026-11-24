"""Tests for node data contracts (Task 40) and schema-conformant mock outputs (Task 41)."""
import glob
import json
import os
import random

import pytest

from app.models.workflow import NodeType, Workflow, WorkflowEdge, WorkflowNode
from app.schemas.simulation import ConditionMode, SimulationSettings
from app.services import schema_utils as su
from app.services.simulator import simulate
from app.services.validator import validate_workflow

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "examples")


def N(id, type, name=None, **kw):
    return WorkflowNode(id=id, type=type, name=name or id, **kw)


# ── Schema shape ─────────────────────────────────────────────────────────────

def test_check_schema_accepts_valid_and_rejects_bad_shapes():
    good = {"type": "object", "properties": {"a": {"type": "string", "enum": ["x"]}, "n": {"type": "array", "items": {"type": "integer"}}},
            "required": ["a"]}
    assert su.check_schema(good) == []
    assert su.check_schema("nope")
    assert su.check_schema({"type": "date"})
    assert su.check_schema({"properties": []})
    assert su.check_schema({"required": "a"})
    assert su.check_schema({"enum": []})
    assert su.check_schema({"minimum": "1"})
    deep = {"type": "object"}
    for _ in range(10):
        deep = {"type": "object", "properties": {"x": deep}}
    assert any("deeply" in p for p in su.check_schema(deep))


# ── Compatibility ────────────────────────────────────────────────────────────

def test_compatibility_problems():
    out = {"type": "object", "properties": {"a": {"type": "string"}, "n": {"type": "integer"}}}
    assert su.compatibility_problems(out, {"properties": {"a": {"type": "string"}}, "required": ["a"]}) == []
    assert su.compatibility_problems(out, {"properties": {"n": {"type": "number"}}}) == []   # integer -> number ok
    assert any("'zzz'" in p for p in su.compatibility_problems(out, {"properties": {"zzz": {}}, "required": ["zzz"]}))
    assert any("'a'" in p for p in su.compatibility_problems(out, {"properties": {"a": {"type": "number"}}}))
    assert su.compatibility_problems(None, {"properties": {}}) == []


def test_validator_reports_edge_contract_mismatch_and_bad_schema():
    wf = Workflow(
        nodes=[
            N("s", NodeType.START),
            N("a", NodeType.API, "Fetch", output_schema={"type": "object", "properties": {"id": {"type": "string"}}}),
            N("b", NodeType.LLM, "Summarise", input_schema={"type": "object", "properties": {"id": {"type": "number"}, "body": {"type": "string"}}, "required": ["body"]}),
            N("c", NodeType.TRANSFORM, "Bad", output_schema={"type": "wibble"}),
            N("e", NodeType.END),
        ],
        edges=[WorkflowEdge(source="s", target="a"), WorkflowEdge(source="a", target="b"),
               WorkflowEdge(source="b", target="c"), WorkflowEdge(source="c", target="e")],
    )
    text = " | ".join(validate_workflow(wf).warnings)
    assert "required field 'body' is not produced upstream" in text
    assert "field 'id' is string upstream but number downstream" in text
    assert "Node 'Bad'" in text and "output schema.type" in text


def test_validator_quiet_when_contracts_compatible():
    wf = Workflow(
        nodes=[
            N("s", NodeType.START),
            N("a", NodeType.API, output_schema={"type": "object", "properties": {"id": {"type": "string"}}}),
            N("b", NodeType.LLM, input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}),
            N("e", NodeType.END),
        ],
        edges=[WorkflowEdge(source="s", target="a"), WorkflowEdge(source="a", target="b"), WorkflowEdge(source="b", target="e")],
    )
    assert not [w for w in validate_workflow(wf).warnings if "Edge" in w or "schema" in w]


def test_schemas_are_optional_and_round_trip():
    node = N("a", NodeType.LLM)
    assert node.input_schema is None and node.output_schema is None
    dumped = N("a", NodeType.LLM, output_schema={"type": "object"}).model_dump(mode="json")
    assert WorkflowNode(**dumped).output_schema == {"type": "object"}


# ── Mock generation ──────────────────────────────────────────────────────────

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "tier": {"type": "string", "enum": ["basic", "premium", "enterprise"]},
        "score": {"type": "number", "minimum": 0, "maximum": 1},
        "count": {"type": "integer", "minimum": 5, "maximum": 9},
        "ok": {"type": "boolean"},
        "tags": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
        "nested": {"type": "object", "properties": {"x": {"type": "integer", "minimum": 1, "maximum": 1}}},
        "fixed": {"const": "always"},
    },
}


def conforms(value, schema) -> bool:
    t = schema.get("type")
    if "const" in schema:
        return value == schema["const"]
    if "enum" in schema:
        return value in schema["enum"]
    if t == "object":
        return isinstance(value, dict) and all(conforms(value[k], s) for k, s in schema.get("properties", {}).items())
    if t == "array":
        return isinstance(value, list) and all(conforms(v, schema.get("items", {})) for v in value) \
            and schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 99)
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool) and schema.get("minimum", -1e9) <= value <= schema.get("maximum", 1e9)
    if t == "number":
        return isinstance(value, (int, float)) and schema.get("minimum", -1e9) <= value <= schema.get("maximum", 1e9)
    return True


@pytest.mark.parametrize("seed", range(25))
def test_generated_values_conform(seed):
    assert conforms(su.generate(SCHEMA, random.Random(seed)), SCHEMA)


def test_generation_is_deterministic_per_seed_and_varies_across_seeds():
    a = su.generate(SCHEMA, random.Random("1:n"))
    assert a == su.generate(SCHEMA, random.Random("1:n"))
    assert len({json.dumps(su.generate(SCHEMA, random.Random(f"{i}:n")), sort_keys=True) for i in range(20)}) > 1


def test_example_and_default_win_over_random():
    assert su.generate({"type": "string", "example": "hi"}, random.Random(0)) == "hi"
    assert su.generate({"type": "integer", "default": 7}, random.Random(0)) == 7


# ── Simulation integration ───────────────────────────────────────────────────

def _routed(llm_node):
    return Workflow(
        nodes=[
            N("s", NodeType.START), llm_node,
            N("c", NodeType.CONDITION, "Route", config={"expression": "input.tier"}),
            N("basic", NodeType.END, "Basic"), N("premium", NodeType.END, "Premium"), N("enterprise", NodeType.END, "Ent"),
        ],
        edges=[WorkflowEdge(source="s", target="l"), WorkflowEdge(source="l", target="c"),
               WorkflowEdge(source="c", target="basic", condition="basic"),
               WorkflowEdge(source="c", target="premium", condition="premium"),
               WorkflowEdge(source="c", target="enterprise", condition="enterprise")],
    )


def _settings(**kw):
    return SimulationSettings(condition_mode=ConditionMode.EXPRESSION, **kw)


@pytest.mark.asyncio
async def test_schema_output_drives_real_branch_and_no_warnings():
    llm = N("l", NodeType.LLM, "Classify", config={"prompt": "p"}, output_schema=SCHEMA)
    trace = await simulate(_routed(llm), {}, _settings())
    cond = next(s for s in trace.steps if s.node_id == "c")
    assert cond.warnings == []
    ends = [s for s in trace.steps if s.node_type == "END"]
    assert len(ends) == 1       # exactly one branch taken, not all


@pytest.mark.asyncio
async def test_same_seed_same_path_and_seeds_can_differ():
    llm = N("l", NodeType.LLM, "Classify", config={"prompt": "p"}, output_schema=SCHEMA)

    async def path(seed):
        t = await simulate(_routed(llm), {}, _settings(seed=seed))
        return [s.node_id for s in t.steps]

    assert await path(3) == await path(3)
    assert len({tuple(await path(i)) for i in range(15)}) > 1


@pytest.mark.asyncio
async def test_pinned_mock_output_wins_over_schema():
    llm = N("l", NodeType.LLM, "Classify", config={"prompt": "p", "mock_output": {"tier": "premium"}}, output_schema=SCHEMA)
    for seed in range(5):
        trace = await simulate(_routed(llm), {}, _settings(seed=seed))
        llm_step = next(s for s in trace.steps if s.node_id == "l")
        assert llm_step.output == {"tier": "premium"}
        assert [s.node_id for s in trace.steps if s.node_type == "END"] == ["premium"]


@pytest.mark.asyncio
async def test_non_dict_pinned_output_is_wrapped_and_default_mock_unchanged():
    wf = Workflow(
        nodes=[N("s", NodeType.START), N("t", NodeType.TOOL, config={"mock_output": "done"}),
               N("l", NodeType.LLM, config={"prompt": "p"}), N("e", NodeType.END)],
        edges=[WorkflowEdge(source="s", target="t"), WorkflowEdge(source="t", target="l"), WorkflowEdge(source="l", target="e")],
    )
    trace = await simulate(wf, {}, _settings())
    assert next(s for s in trace.steps if s.node_id == "t").output == {"result": "done"}
    assert "Mock LLM output" in next(s for s in trace.steps if s.node_id == "l").output["result"]


@pytest.mark.asyncio
async def test_invalid_schema_falls_back_to_default_mock():
    llm = N("l", NodeType.LLM, config={"prompt": "p"}, output_schema={"type": "wibble"})
    wf = Workflow(nodes=[N("s", NodeType.START), llm, N("e", NodeType.END)],
                  edges=[WorkflowEdge(source="s", target="l"), WorkflowEdge(source="l", target="e")])
    trace = await simulate(wf, {}, _settings())
    assert trace.status == "complete"
    assert "Mock LLM output" in next(s for s in trace.steps if s.node_id == "l").output["result"]


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(EXAMPLES, "**", "*.json"), recursive=True)))
@pytest.mark.asyncio
async def test_examples_now_take_real_branches_without_warnings(path):
    wf = Workflow(**json.load(open(path, encoding="utf-8")))
    trace = await simulate(wf, {}, _settings())
    assert trace.status == "complete"
    for step in trace.steps:
        if step.node_type == "CONDITION":
            assert step.warnings == [], (path, step.node_name, step.warnings)
