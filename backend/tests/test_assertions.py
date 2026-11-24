"""Tests for deterministic suite assertions (Task 50)."""
import pytest
from pydantic import ValidationError

from app.schemas.suites import Assertion, SuiteCase
from app.services import schema_utils as su
from app.services.assertions import (
    AssertionContext, definition_problems, describe, evaluate_assertions, get_path,
)


def ctx(output=None, **kw):
    return AssertionContext(output=output, **kw)


def run(assertion, output=None, **kw):
    [r] = evaluate_assertions([assertion], ctx(output, **kw))
    return r


# ── get_path ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path,expected", [
    (None, (True, {"a": {"b": [10, {"c": 5}]}})),
    ("", (True, {"a": {"b": [10, {"c": 5}]}})),
    ("a.b.0", (True, 10)),
    ("a.b[1].c", (True, 5)),
    ("a.zzz", (False, None)),
    ("a.b.9", (False, None)),
    ("a.b.x", (False, None)),
    ("a.b.0.deeper", (False, None)),
])
def test_get_path(path, expected):
    assert get_path({"a": {"b": [10, {"c": 5}]}}, path) == expected


# ── Each assertion type ──────────────────────────────────────────────────────

def test_equals():
    assert run({"type": "equals", "path": "status", "value": "ok"}, {"status": "ok"}).passed
    r = run({"type": "equals", "path": "status", "value": "ok"}, {"status": "bad"})
    assert not r.passed and "expected 'ok'" in r.message
    assert run({"type": "equals", "value": None}, None).passed                  # null is a valid expected value
    assert not run({"type": "equals", "path": "missing", "value": 1}, {}).passed


def test_contains():
    assert run({"type": "contains", "path": "t", "value": "ell"}, {"t": "hello"}).passed
    assert run({"type": "contains", "path": "l", "value": 2}, {"l": [1, 2]}).passed
    assert run({"type": "contains", "value": "k"}, {"k": 1}).passed             # object has key
    assert not run({"type": "contains", "path": "t", "value": "z"}, {"t": "hello"}).passed
    assert "cannot contain" in run({"type": "contains", "path": "n", "value": 1}, {"n": 5}).message


def test_exists():
    assert run({"type": "exists", "path": "a.b"}, {"a": {"b": 0}}).passed
    assert not run({"type": "exists", "path": "a.b"}, {"a": {}}).passed
    assert run({"type": "exists", "path": "secret", "value": False}, {"x": 1}).passed
    assert not run({"type": "exists", "path": "secret", "value": False}, {"secret": 1}).passed


@pytest.mark.parametrize("op,expected,passes", [
    ("==", 5, True), ("!=", 5, False), ("<", 6, True), ("<=", 5, True), (">", 5, False), (">=", 5, True),
])
def test_compare(op, expected, passes):
    assert run({"type": "compare", "path": "n", "op": op, "value": expected}, {"n": 5}).passed is passes


def test_compare_rejects_non_numbers_and_booleans():
    assert "not a number" in run({"type": "compare", "path": "n", "op": ">", "value": 1}, {"n": "5"}).message
    assert not run({"type": "compare", "path": "n", "op": "==", "value": 1}, {"n": True}).passed


def test_one_of():
    assert run({"type": "one_of", "path": "tier", "values": ["a", "b"]}, {"tier": "b"}).passed
    assert not run({"type": "one_of", "path": "tier", "values": ["a", "b"]}, {"tier": "c"}).passed


def test_matches_schema():
    schema = {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}, "n": {"type": "integer", "minimum": 1}}}
    assert run({"type": "matches_schema", "output_schema": schema}, {"id": "x", "n": 3}).passed
    r = run({"type": "matches_schema", "output_schema": schema}, {"n": 0})
    assert not r.passed and "missing required field 'id'" in r.message and "+1 more" in r.message
    assert not run({"type": "matches_schema", "path": "x", "output_schema": {"type": "string"}}, {"x": 5}).passed


def test_expression_uses_output_input_visited_steps_status():
    out = {"n": 4}
    ok = run({"type": "expression", "expression": "output.n > 3 and input.q == 'hi' and 'a' in visited and steps == 3 and status == 'complete'"},
             out, input={"q": "hi"}, visited=["a", "b"], step_count=3)
    assert ok.passed, ok.message
    assert not run({"type": "expression", "expression": "output.n > 10"}, out).passed


def test_expression_errors_fail_cleanly_and_cannot_escape():
    r = run({"type": "expression", "expression": "output.missing > 1"}, {})
    assert not r.passed and "could not be evaluated" in r.message
    r = run({"type": "expression", "expression": "().__class__"}, {})   # refused when the definition is checked
    assert not r.passed and "not allowed" in r.message


def test_node_and_step_assertions():
    visited = ["s", "a", "e"]
    assert run({"type": "visits_node", "node_id": "a"}, visited=visited).passed
    assert not run({"type": "visits_node", "node_id": "b"}, visited=visited).passed
    assert run({"type": "skips_node", "node_id": "b"}, visited=visited).passed
    assert not run({"type": "skips_node", "node_id": "a"}, visited=visited).passed
    assert run({"type": "max_steps", "max_steps": 3}, step_count=3).passed
    assert not run({"type": "max_steps", "max_steps": 2}, step_count=3).passed


def test_label_and_description():
    r = run({"type": "equals", "path": "x", "value": 1, "label": "  my check  "}, {"x": 1})
    assert r.label == "my check"
    assert run({"type": "equals", "path": "x", "value": 1}, {"x": 1}).label == "equals x 1"
    assert describe({"type": "visits_node", "node_id": "n"}) == "visits_node n"


def test_results_keep_order_and_index_and_one_failure_does_not_stop_the_rest():
    results = evaluate_assertions(
        [{"type": "equals", "path": "a", "value": 2}, {"type": "exists", "path": "b"}], ctx({"a": 1, "b": 1}),
    )
    assert [(r.index, r.passed) for r in results] == [(0, False), (1, True)]


def test_invalid_stored_assertion_fails_instead_of_crashing():
    r = run({"type": "compare", "path": "n"}, {"n": 1})
    assert not r.passed and r.message.startswith("invalid assertion")
    assert not run({"type": "nope"}, {}).passed


# ── Definition validation ────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    {"type": "bogus"}, {},
    {"type": "equals"}, {"type": "contains"},
    {"type": "exists"}, {"type": "exists", "path": "a", "value": "yes"},
    {"type": "compare", "path": "a", "op": "~", "value": 1}, {"type": "compare", "path": "a", "op": ">", "value": "1"},
    {"type": "compare", "op": ">", "value": 1}, {"type": "compare", "path": "a", "op": ">", "value": True},
    {"type": "one_of", "values": []}, {"type": "one_of"},
    {"type": "matches_schema"}, {"type": "matches_schema", "output_schema": {"type": "wibble"}},
    {"type": "expression"}, {"type": "expression", "expression": "a && b"}, {"type": "expression", "expression": "f(x)"},
    {"type": "visits_node"}, {"type": "skips_node", "node_id": 5},
    {"type": "max_steps", "max_steps": 0}, {"type": "max_steps", "max_steps": "3"}, {"type": "max_steps", "max_steps": True},
    {"type": "equals", "value": 1, "path": 5}, {"type": "equals", "value": 1, "label": "x" * 201},
])
def test_invalid_definitions_are_reported(bad):
    assert definition_problems(bad)


@pytest.mark.parametrize("good", [
    {"type": "equals", "value": None}, {"type": "contains", "value": "x"}, {"type": "exists", "path": "a"},
    {"type": "compare", "path": "a", "op": ">=", "value": 1.5}, {"type": "one_of", "values": [1]},
    {"type": "matches_schema", "output_schema": {"type": "object"}}, {"type": "expression", "expression": "output.a == 1"},
    {"type": "visits_node", "node_id": "n"}, {"type": "max_steps", "max_steps": 5},
])
def test_valid_definitions_pass(good):
    assert definition_problems(good) == []


def test_pydantic_models_enforce_definitions_and_limits():
    with pytest.raises(ValidationError):
        Assertion(type="equals")                         # value required
    with pytest.raises(ValidationError):
        Assertion(type="equals", value=1, surprise=True)  # unknown fields rejected
    Assertion(type="equals", value=None)                 # explicit null is fine
    with pytest.raises(ValidationError):
        SuiteCase(name="x", assertions=[{"type": "max_steps", "max_steps": 1}] * 21)
    with pytest.raises(ValidationError):
        SuiteCase(name="", input={})
    with pytest.raises(ValidationError):
        SuiteCase(name="x", input={"big": "y" * 25_000})
    with pytest.raises(ValidationError):
        SuiteCase(name="x", tags=["ok", " "])
    with pytest.raises(ValidationError):
        SuiteCase(name="x", seed=-1)


# ── schema_utils.validate_value ──────────────────────────────────────────────

def test_validate_value_covers_the_generator_keywords():
    schema = {"type": "object", "required": ["a"], "properties": {
        "a": {"type": "string", "enum": ["x", "y"]}, "n": {"type": "number", "minimum": 0, "maximum": 1},
        "l": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "integer"}}, "k": {"const": 7}}}
    assert su.validate_value(schema, {"a": "x", "n": 0.5, "l": [1], "k": 7}) == []
    problems = su.validate_value(schema, {"a": "z", "n": 2, "l": [1, "no", 3], "k": 8})
    text = " | ".join(problems)
    assert "not one of" in text and "above the maximum" in text and "more than 2" in text
    assert "$.l[1]: expected integer" in text and "expected 7" in text
    assert su.validate_value({"type": "integer"}, True)          # bool is not an integer
    assert su.validate_value({"type": "string"}, 5) == ["$: expected string, got int"]
    assert su.validate_value("not a schema", 5) == []


def test_generated_values_always_validate_against_their_schema():
    import random
    schema = {"type": "object", "properties": {"n": {"type": "integer", "minimum": 3, "maximum": 9},
              "t": {"type": "string"}, "e": {"enum": ["a", "b"]}, "l": {"type": "array", "items": {"type": "number"}}}}
    for seed in range(30):
        assert su.validate_value(schema, su.generate(schema, random.Random(seed))) == []
