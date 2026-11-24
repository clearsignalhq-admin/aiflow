"""Deterministic assertions for test-suite cases (Task 50).

An assertion checks the *final output* of a simulated case (the ``result`` of the END node
reached), its path through the workflow, or its size. There is no LLM judge: every verdict
is reproducible. See docs/AiFlow - Async Suite Runs Design.md.

Assertion shapes (all take an optional ``label``):

    equals          path?, value          output at path == value
    contains        path?, value          text contains / list has / object has key
    exists          path,  value?=true    path resolves (false: path must be absent)
    compare         path,  op, value      numeric: == != < <= > >=
    one_of          path?, values         output at path is one of the values
    matches_schema  path?, output_schema  value conforms to a JSON-Schema subset
    expression      expression            safe expression (see expressions.py) is truthy;
                                          names: input, output, visited, steps, status
    visits_node     node_id               the case executed this node
    skips_node      node_id               the case did not execute this node
    max_steps       max_steps             at most N nodes were executed

``path`` is dotted with numeric list indexes: ``order.items.0.sku`` (``items[0]`` also works).
Empty path means the whole output.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel

from app.services import expressions, schema_utils

ASSERTION_TYPES = (
    "equals", "contains", "exists", "compare", "one_of",
    "matches_schema", "expression", "visits_node", "skips_node", "max_steps",
)
COMPARE_OPS = ("==", "!=", "<", "<=", ">", ">=")
MAX_ASSERTIONS_PER_CASE = 20
_MISSING = object()


@dataclass
class AssertionContext:
    output: Any
    input: dict[str, Any] = field(default_factory=dict)
    visited: list[str] = field(default_factory=list)
    step_count: int = 0
    status: str = "complete"


class AssertionResult(BaseModel):
    index: int
    type: str
    label: str
    passed: bool
    message: str


# ── Definition validation (used when a suite is saved) ───────────────────────

def definition_problems(a: dict[str, Any]) -> list[str]:
    """Problems that make an assertion definition unusable. Empty list = valid."""
    kind = a.get("type")
    if kind not in ASSERTION_TYPES:
        return [f"unknown assertion type {kind!r}"]
    problems: list[str] = []

    def need(key: str, typ: type | tuple = object) -> bool:
        if key not in a or a[key] is None and key != "value":
            problems.append(f"{kind}: '{key}' is required")
            return False
        if not isinstance(a[key], typ):
            problems.append(f"{kind}: '{key}' has the wrong type")
            return False
        return True

    path = a.get("path")
    if path is not None and not isinstance(path, str):
        problems.append(f"{kind}: 'path' must be text")

    if kind in ("equals", "contains"):
        if "value" not in a:
            problems.append(f"{kind}: 'value' is required")
    elif kind == "exists":
        if not isinstance(path, str) or not path.strip():
            problems.append("exists: 'path' is required")
        if "value" in a and not isinstance(a["value"], bool):
            problems.append("exists: 'value' must be true or false")
    elif kind == "compare":
        if not isinstance(path, str) or not path.strip():
            problems.append("compare: 'path' is required")
        if a.get("op") not in COMPARE_OPS:
            problems.append(f"compare: 'op' must be one of {', '.join(COMPARE_OPS)}")
        if isinstance(a.get("value"), bool) or not isinstance(a.get("value"), (int, float)):
            problems.append("compare: 'value' must be a number")
    elif kind == "one_of":
        if not isinstance(a.get("values"), list) or not a["values"]:
            problems.append("one_of: 'values' must be a non-empty list")
    elif kind == "matches_schema":
        if need("output_schema", dict):
            problems += [f"matches_schema: {p}" for p in schema_utils.check_schema(a["output_schema"], "output_schema")]
    elif kind == "expression":
        if need("expression", str):
            problem = expressions.check_syntax(a["expression"])
            if problem:
                problems.append(f"expression: {problem}")
    elif kind in ("visits_node", "skips_node"):
        need("node_id", str)
    elif kind == "max_steps":
        n = a.get("max_steps")
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            problems.append("max_steps: 'max_steps' must be an integer of at least 1")

    label = a.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > 200):
        problems.append(f"{kind}: 'label' must be text of at most 200 characters")
    return problems


# ── Path access ──────────────────────────────────────────────────────────────

def get_path(obj: Any, path: Optional[str]) -> tuple[bool, Any]:
    """Resolve a dotted path. Returns (found, value). Plain dict/list traversal only."""
    if path is None or not path.strip():
        return True, obj
    tokens = [t for t in re.sub(r"\[(\d+)\]", r".\1", path.strip()).split(".") if t != ""]
    current = obj
    for token in tokens:
        if isinstance(current, dict):
            if token not in current:
                return False, None
            current = current[token]
        elif isinstance(current, list) and token.isdigit():
            index = int(token)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


# ── Evaluation ───────────────────────────────────────────────────────────────

def _show(value: Any, limit: int = 80) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _where(path: Optional[str]) -> str:
    return f"output.{path}" if path and path.strip() else "output"


def _evaluate_one(a: dict[str, Any], ctx: AssertionContext) -> tuple[bool, str]:
    kind = a["type"]
    path = a.get("path")
    found, actual = get_path(ctx.output, path)
    where = _where(path)

    if kind == "visits_node":
        ok = a["node_id"] in ctx.visited
        return ok, f"node '{a['node_id']}' {'was' if ok else 'was not'} executed"
    if kind == "skips_node":
        ok = a["node_id"] not in ctx.visited
        return ok, f"node '{a['node_id']}' {'was skipped' if ok else 'was executed'}"
    if kind == "max_steps":
        ok = ctx.step_count <= a["max_steps"]
        return ok, f"{ctx.step_count} steps executed (max {a['max_steps']})"
    if kind == "expression":
        context = {
            "input": ctx.input, "output": ctx.output, "visited": ctx.visited,
            "steps": ctx.step_count, "status": ctx.status,
        }
        try:
            result = expressions.evaluate(a["expression"], context)
        except expressions.ExpressionError as exc:
            return False, f"expression could not be evaluated: {exc}"
        return bool(result), f"expression is {'true' if result else 'false'}"
    if kind == "exists":
        want = a.get("value", True)
        return found == want, f"{where} {'exists' if found else 'does not exist'}"

    if not found:
        return False, f"{where} does not exist"

    if kind == "equals":
        ok = actual == a["value"]
        return ok, f"{where} is {_show(actual)}" + ("" if ok else f", expected {_show(a['value'])}")
    if kind == "contains":
        needle = a["value"]
        if isinstance(actual, str):
            ok = str(needle) in actual
        elif isinstance(actual, list):
            ok = needle in actual
        elif isinstance(actual, dict):
            ok = needle in actual
        else:
            return False, f"{where} is {_show(actual)}, which cannot contain anything"
        return ok, f"{where} {'contains' if ok else 'does not contain'} {_show(needle)}"
    if kind == "one_of":
        ok = actual in a["values"]
        return ok, f"{where} is {_show(actual)}" + ("" if ok else f", expected one of {_show(a['values'])}")
    if kind == "compare":
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False, f"{where} is {_show(actual)}, not a number"
        op, expected = a["op"], a["value"]
        ok = {
            "==": actual == expected, "!=": actual != expected, "<": actual < expected,
            "<=": actual <= expected, ">": actual > expected, ">=": actual >= expected,
        }[op]
        return ok, f"{where} is {_show(actual)}" + ("" if ok else f", expected {op} {_show(expected)}")
    if kind == "matches_schema":
        problems = schema_utils.validate_value(a["output_schema"], actual)
        if not problems:
            return True, f"{where} matches the schema"
        return False, f"{where} does not match the schema: {problems[0]}" + (f" (+{len(problems) - 1} more)" if len(problems) > 1 else "")
    return False, f"unsupported assertion type {kind!r}"


def describe(a: dict[str, Any]) -> str:
    """Short human-readable name for an assertion (used when it has no label)."""
    kind = a.get("type", "?")
    path = a.get("path")
    target = f" {path}" if path else ""
    if kind in ("equals", "contains"):
        return f"{kind}{target} {_show(a.get('value'), 30)}"
    if kind == "compare":
        return f"compare{target} {a.get('op')} {_show(a.get('value'), 30)}"
    if kind == "one_of":
        return f"one_of{target} {_show(a.get('values'), 30)}"
    if kind in ("visits_node", "skips_node"):
        return f"{kind} {a.get('node_id')}"
    if kind == "max_steps":
        return f"max_steps {a.get('max_steps')}"
    if kind == "expression":
        return f"expression {_show(a.get('expression'), 40)}"
    return f"{kind}{target}"


def evaluate_assertions(assertions: list[dict[str, Any]], ctx: AssertionContext) -> list[AssertionResult]:
    results: list[AssertionResult] = []
    for index, a in enumerate(assertions):
        label = (a.get("label") or "").strip() or describe(a)
        problems = definition_problems(a)
        if problems:
            results.append(AssertionResult(index=index, type=str(a.get("type")), label=label, passed=False,
                                           message=f"invalid assertion: {problems[0]}"))
            continue
        try:
            passed, message = _evaluate_one(a, ctx)
        except Exception as exc:  # an assertion must never take the whole case down
            passed, message = False, f"assertion failed to run: {exc}"
        results.append(AssertionResult(index=index, type=a["type"], label=label, passed=passed, message=message))
    return results
