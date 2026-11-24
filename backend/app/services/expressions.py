"""Safe expression evaluator for CONDITION nodes.

Replaces the former ``eval()`` call. Expressions are parsed with ``ast`` and
walked against an explicit whitelist; nothing is ever compiled or executed as
Python code.

Language (a small Python-style subset)
--------------------------------------
- literals: numbers, strings, ``True``/``False``/``None`` (``true``/``false``/``null`` also accepted)
- names: fields of the CONDITION node's input, plus ``input`` / ``output`` (the whole dict)
- field access: ``input.status``, ``input["status"]``, list index ``items[0]``
- operators: ``== != < <= > >= in not in``, ``and or not``, ``+ - * / // %``, unary ``- +``
- conditional: ``"a" if x > 1 else "b"``, list/tuple literals

Not allowed: calls, lambdas, comprehensions, f-strings, slices, ``**``,
``is``, and any name or key starting with ``_``.
"""
import ast
from typing import Any

MAX_EXPRESSION_LENGTH = 500
MAX_AST_NODES = 100
_MAX_SEQUENCE_REPEAT = 1000

_CONSTANT_NAMES: dict[str, Any] = {"true": True, "false": False, "null": None}

_BOOL_TRUE_LABELS = {"true", "yes"}
_BOOL_FALSE_LABELS = {"false", "no"}
DEFAULT_LABELS = {"else", "default", "otherwise"}


class ExpressionError(Exception):
    """Raised for syntax errors, disallowed constructs, and evaluation failures."""


_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Constant, ast.Name, ast.Attribute, ast.Subscript, ast.List, ast.Tuple,
    ast.IfExp, ast.Load,
)

_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
}

_CMPOPS = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


# ── Parsing / static checks ───────────────────────────────────────────────────

def parse(expression: str) -> ast.Expression:
    """Parse and statically validate an expression. Raises ExpressionError."""
    if not isinstance(expression, str) or not expression.strip():
        raise ExpressionError("Expression is empty.")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(f"Expression is longer than {MAX_EXPRESSION_LENGTH} characters.")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        raise ExpressionError(f"Invalid syntax: {getattr(exc, 'msg', None) or exc.__class__.__name__}") from None

    count = 0
    for node in ast.walk(tree):
        count += 1
        if count > MAX_AST_NODES:
            raise ExpressionError("Expression is too complex.")
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"'{type(node).__name__}' is not allowed in expressions.")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ExpressionError(f"Name '{node.id}' is not allowed.")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ExpressionError(f"Attribute '{node.attr}' is not allowed.")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (str, int, float, bool, type(None))):
            raise ExpressionError("Unsupported literal.")
    return tree


def check_syntax(expression: str) -> str | None:
    """Return an error message if the expression can never be evaluated, else None."""
    try:
        parse(expression)
    except ExpressionError as exc:
        return str(exc)
    return None


def possible_results(expression: str) -> set[Any] | None:
    """Statically infer the set of values an expression can produce, or None if unknown.

    Comparisons and boolean operators yield {True, False}; constants and
    conditional expressions over constants yield their literal values.
    """
    try:
        tree = parse(expression)
    except ExpressionError:
        return None
    return _possible(tree.body)


def _possible(node: ast.AST) -> set[Any] | None:
    if isinstance(node, (ast.Compare, ast.BoolOp)):
        return {True, False}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return {True, False}
    if isinstance(node, ast.Constant):
        return {node.value}
    if isinstance(node, ast.IfExp):
        a, b = _possible(node.body), _possible(node.orelse)
        return None if a is None or b is None else a | b
    return None


# ── Label matching (the routing contract) ─────────────────────────────────────

def _norm(value: Any) -> str:
    return str(value).strip().lower()


def label_candidates(value: Any) -> set[str]:
    """Edge labels (normalised, case-insensitive) that a result value routes to."""
    if value is True:
        return set(_BOOL_TRUE_LABELS)
    if value is False:
        return set(_BOOL_FALSE_LABELS)
    if value is None:
        return {"none", "null"}
    if isinstance(value, float) and value.is_integer():
        return {_norm(value), _norm(int(value))}
    return {_norm(value)}


def normalise_label(label: Any) -> str:
    return _norm(label) if label is not None else ""


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate(expression: str, context: dict[str, Any]) -> Any:
    """Evaluate ``expression`` against ``context``. Raises ExpressionError on any failure."""
    tree = parse(expression)
    try:
        return _eval(tree.body, context)
    except ExpressionError:
        raise
    except RecursionError:
        raise ExpressionError("Expression is too deeply nested.") from None
    except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ExpressionError(f"Could not evaluate expression: {exc}") from None


def _eval(node: ast.AST, ctx: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id in _CONSTANT_NAMES:
            return _CONSTANT_NAMES[node.id]
        if node.id in ctx:
            return ctx[node.id]
        raise ExpressionError(f"Unknown name '{node.id}'.")

    if isinstance(node, ast.Attribute):
        return _get_key(_eval(node.value, ctx), node.attr)

    if isinstance(node, ast.Subscript):
        return _get_item(_eval(node.value, ctx), _eval(node.slice, ctx))

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(e, ctx) for e in node.elts]

    if isinstance(node, ast.IfExp):
        return _eval(node.body if _eval(node.test, ctx) else node.orelse, ctx)

    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, ctx)
        if isinstance(node.op, ast.Not):
            return not operand
        _require_number(operand)
        return -operand if isinstance(node.op, ast.USub) else +operand

    if isinstance(node, ast.BoolOp):
        # Short-circuit, returning the deciding operand (Python semantics).
        result: Any = None
        for value_node in node.values:
            result = _eval(value_node, ctx)
            if isinstance(node.op, ast.And) and not result:
                return result
            if isinstance(node.op, ast.Or) and result:
                return result
        return result

    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, ctx), _eval(node.right, ctx)
        if isinstance(node.op, ast.Mult):
            _guard_repeat(left, right)
        return _BINOPS[type(node.op)](left, right)

    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, ctx)
            if not _CMPOPS[type(op)](left, right):
                return False
            left = right
        return True

    raise ExpressionError(f"'{type(node).__name__}' is not allowed in expressions.")


def _get_key(obj: Any, key: str) -> Any:
    if key.startswith("_"):
        raise ExpressionError(f"Field '{key}' is not allowed.")
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        raise ExpressionError(f"No field '{key}'.")
    raise ExpressionError(f"Cannot read field '{key}' of a {type(obj).__name__}.")


def _get_item(obj: Any, index: Any) -> Any:
    if isinstance(obj, dict):
        if not isinstance(index, str):
            raise ExpressionError("Dictionary keys must be strings.")
        return _get_key(obj, index)
    if isinstance(obj, list):
        if isinstance(index, bool) or not isinstance(index, int):
            raise ExpressionError("List indexes must be integers.")
        try:
            return obj[index]
        except IndexError:
            raise ExpressionError(f"List index {index} is out of range.") from None
    raise ExpressionError(f"Cannot index a {type(obj).__name__}.")


def _require_number(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExpressionError("Unary +/- needs a number.")


def _guard_repeat(left: Any, right: Any) -> None:
    for seq, count in ((left, right), (right, left)):
        if isinstance(seq, (str, list)) and isinstance(count, int) and not isinstance(count, bool):
            if count * max(len(seq), 1) > _MAX_SEQUENCE_REPEAT:
                raise ExpressionError("Repeated sequence is too large.")
