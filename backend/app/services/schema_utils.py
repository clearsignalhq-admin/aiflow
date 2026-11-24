"""Helpers for the small JSON-Schema subset used by node data contracts.

Supported keywords: ``type`` (string, number, integer, boolean, object, array, null),
``properties``, ``required``, ``items``, ``enum``, ``const``, ``default``, ``example``,
``minimum``, ``maximum``, ``minItems``, ``maxItems``. Anything else is ignored.

Kept dependency-free on purpose (the Lambda package stays small) and deterministic:
mock data generation takes an explicit ``random.Random``.
"""
import random
from typing import Any

SCHEMA_TYPES = {"string", "number", "integer", "boolean", "object", "array", "null"}
_MAX_DEPTH = 6
_MAX_ARRAY_ITEMS = 3


# ── Shape check ──────────────────────────────────────────────────────────────

def check_schema(schema: Any, path: str = "schema", depth: int = 0) -> list[str]:
    """Return human-readable problems with the schema's shape (empty list = fine)."""
    if not isinstance(schema, dict):
        return [f"{path} must be an object."]
    if depth > _MAX_DEPTH:
        return [f"{path} is nested too deeply (max {_MAX_DEPTH} levels)."]

    problems: list[str] = []
    type_ = schema.get("type")
    if type_ is not None and (not isinstance(type_, str) or type_ not in SCHEMA_TYPES):
        problems.append(f"{path}.type must be one of {', '.join(sorted(SCHEMA_TYPES))}.")

    props = schema.get("properties")
    if props is not None:
        if not isinstance(props, dict):
            problems.append(f"{path}.properties must be an object.")
        else:
            for key, sub in props.items():
                problems.extend(check_schema(sub, f"{path}.properties.{key}", depth + 1))

    required = schema.get("required")
    if required is not None and (not isinstance(required, list) or not all(isinstance(r, str) for r in required)):
        problems.append(f"{path}.required must be a list of strings.")

    if "items" in schema:
        problems.extend(check_schema(schema["items"], f"{path}.items", depth + 1))

    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum):
        problems.append(f"{path}.enum must be a non-empty list.")

    for key in ("minimum", "maximum"):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], (int, float))):
            problems.append(f"{path}.{key} must be a number.")

    return problems


# ── Introspection / compatibility ────────────────────────────────────────────

def property_names(schema: Any) -> set[str] | None:
    """Names declared under ``properties``, or None when the schema declares none."""
    if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
        return set(schema["properties"].keys())
    return None


def _types_compatible(out_type: Any, in_type: Any) -> bool:
    if out_type is None or in_type is None or out_type == in_type:
        return True
    return out_type == "integer" and in_type == "number"


def compatibility_problems(output_schema: Any, input_schema: Any) -> list[str]:
    """Problems that would stop data shaped like ``output_schema`` satisfying ``input_schema``."""
    out_props = property_names(output_schema)
    in_props = property_names(input_schema)
    if out_props is None or in_props is None:
        return []

    problems: list[str] = []
    required = input_schema.get("required") or []
    for name in required:
        if name not in out_props:
            problems.append(f"required field '{name}' is not produced upstream")

    for name in sorted(out_props & in_props):
        out_type = (output_schema["properties"][name] or {}).get("type")
        in_type = (input_schema["properties"][name] or {}).get("type")
        if not _types_compatible(out_type, in_type):
            problems.append(f"field '{name}' is {out_type} upstream but {in_type} downstream")
    return problems


# ── Deterministic mock data ──────────────────────────────────────────────────

def generate(schema: Any, rng: random.Random, name: str = "value", depth: int = 0) -> Any:
    """Generate a value conforming to ``schema`` using ``rng`` for all choices."""
    if not isinstance(schema, dict) or depth > _MAX_DEPTH:
        return f"sample {name}"

    if "const" in schema:
        return schema["const"]
    if "example" in schema:
        return schema["example"]
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return rng.choice(schema["enum"])
    if "default" in schema:
        return schema["default"]

    type_ = schema.get("type")
    if type_ is None:
        if "properties" in schema:
            type_ = "object"
        elif "items" in schema:
            type_ = "array"
        else:
            return f"sample {name}"

    if type_ == "string":
        return f"sample {name}"
    if type_ == "boolean":
        return rng.choice([True, False])
    if type_ == "null":
        return None
    if type_ in ("number", "integer"):
        lo = schema.get("minimum", 0)
        hi = schema.get("maximum", max(lo + 100, 100))
        if hi < lo:
            hi = lo
        if type_ == "integer":
            return rng.randint(int(lo), int(hi))
        return round(rng.uniform(lo, hi), 2)
    if type_ == "array":
        low = int(schema.get("minItems", 1))
        high = max(low, min(int(schema.get("maxItems", _MAX_ARRAY_ITEMS)), _MAX_ARRAY_ITEMS))
        count = rng.randint(low, high)
        return [generate(schema.get("items"), rng, name, depth + 1) for _ in range(count)]
    if type_ == "object":
        props = schema.get("properties") or {}
        return {key: generate(sub, rng, key, depth + 1) for key, sub in props.items()}
    return f"sample {name}"
