"""Argument models and the JSON schemas bound to chat models."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class ToolArgs(BaseModel):
    """Base of every tool's arguments. Unknown arguments are an error the model can read."""

    model_config = ConfigDict(extra="forbid")


def _simplify(node: Any, defs: dict[str, Any]) -> Any:
    """Reduce a pydantic JSON schema to the subset every chat provider accepts.

    Keeps type, description, enum, items, properties and required. Drops titles, defaults and
    length limits (those are described in words and enforced by validation), unwraps
    `anyOf [X, null]`, and inlines `$ref`.
    """
    if isinstance(node, list):
        return [_simplify(n, defs) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return _simplify(defs[node["$ref"].split("/")[-1]], defs)
    if "anyOf" in node:
        options = [o for o in node["anyOf"] if o.get("type") != "null"]
        merged = _simplify(options[0], defs) if options else {"type": "string"}
        if "description" in node and isinstance(merged, dict):
            merged["description"] = node["description"]
        return merged
    out: dict[str, Any] = {}
    for key in ("type", "description", "enum", "format"):
        if key in node:
            out[key] = node[key]
    if "items" in node:
        out["items"] = _simplify(node["items"], defs)
    if "properties" in node:
        out["properties"] = {k: _simplify(v, defs) for k, v in node["properties"].items()}
        out["required"] = list(node.get("required", []))
    return out


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    return _simplify(raw, raw.get("$defs", {}))  # type: ignore[no-any-return]
