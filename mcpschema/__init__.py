"""Dependency-free JSON Schema derivation for MCP tool signatures.

A leaf package (stdlib only) so ``api`` can build MCP ``inputSchema`` values
without importing ``agenttools.mcp_app``, which owns the tool registry.
"""

from __future__ import annotations

import inspect
from typing import Any


JSON_TYPES: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def json_type(annotation: Any) -> str:
    """Best-effort JSON Schema type for a parameter annotation.

    Annotations here are evaluated lazily (``from __future__ import
    annotations``), so they arrive as strings. Unions and anything unrecognised
    fall back to "string", which keeps the tool callable rather than
    advertising a type the caller cannot satisfy.
    """
    if not isinstance(annotation, str):
        return JSON_TYPES.get(annotation, "string")
    text = annotation.split("|")[0].strip().lower()
    for py_type, json_type in JSON_TYPES.items():
        if text.startswith(py_type.__name__):
            return json_type
    return "string"


# Parameters that exist for the process, not the caller. `provider` is
# generate_cover_letter's dependency-injection seam for tests; advertising it
# would invite the agent to pass one. Excluded from every tool's schema.
INTERNAL_PARAMS = frozenset({"provider"})


def input_schema(fn: Any) -> dict:
    """Derive a tool's inputSchema from its signature.

    Without this every tool advertised an empty property set, so a caller
    reading the schema had no way to know that seven of the nine take
    arguments — it would call them bare and get a TypeError back. Parameters
    with no default are required; a ``**kwargs`` tool accepts any field.
    """
    properties: dict[str, dict] = {}
    required: list[str] = []
    additional = False
    for name, param in inspect.signature(fn).parameters.items():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            additional = True
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        if name in INTERNAL_PARAMS:
            continue
        properties[name] = {"type": json_type(param.annotation)}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": required,
    }
    if additional:
        schema["additionalProperties"] = True
    return schema
