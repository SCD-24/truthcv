"""MCP application with tool wrappers for streamable-HTTP integration.

This module builds a Starlette ASGI app that exposes the agent tool surface
as an MCP streamable-HTTP JSON-RPC endpoint.
"""

from __future__ import annotations

import inspect
from typing import Any

from mcp import types
from mcp.server import Server

from agenttools.tools_boards import record_company_board as _record_company_board
from agenttools.tools_ledger import (
    check_cooldown as _check_cooldown,
    get_canonical_cv as _get_canonical_cv,
    get_job_profiles as _get_job_profiles,
    get_profile_answers as _get_profile_answers,
    recommend_salary as _recommend_salary,
    record_application as _record_application,
    record_screening as _record_screening,
)
from agenttools.tools_letter import generate_cover_letter as _generate_cover_letter


_TOOL_REGISTRY = {
    "generate_cover_letter": (
        _generate_cover_letter,
        "Generates a guardrailed, per-role cover letter.",
    ),
    "record_application": (
        _record_application,
        "Records a submitted application and its evidence trail.",
    ),
    "record_screening": (
        _record_screening,
        "Records a rejected or deferred posting.",
    ),
    "check_cooldown": (
        _check_cooldown,
        "Checks whether a company/role is in cooldown.",
    ),
    "get_canonical_cv": (
        _get_canonical_cv,
        "Returns the stored canonical CV asset to attach.",
    ),
    "get_profile_answers": (
        _get_profile_answers,
        "Returns the operator's canonical screening answers from the answers store. Never assume or hard-code any of these — always call this tool.",
    ),
    "get_job_profiles": (
        _get_job_profiles,
        "Returns the configured job search profiles and their full criteria (salary band, remote model, employment country, and the rest).",
    ),
    "recommend_salary": (
        _recommend_salary,
        "Given the matched profile's name (and optionally a derived proposed figure), returns the operator's salary ask for that profile, clamped to its configured band.",
    ),
    "record_company_board": (
        _record_company_board,
        "Records a target company's careers URL and ATS once verified on the employer's own site.",
    ),
}


_JSON_TYPES: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _json_type(annotation: Any) -> str:
    """Best-effort JSON Schema type for a parameter annotation.

    Annotations here are evaluated lazily (``from __future__ import
    annotations``), so they arrive as strings. Unions and anything unrecognised
    fall back to "string", which keeps the tool callable rather than
    advertising a type the caller cannot satisfy.
    """
    if not isinstance(annotation, str):
        return _JSON_TYPES.get(annotation, "string")
    text = annotation.split("|")[0].strip().lower()
    for py_type, json_type in _JSON_TYPES.items():
        if text.startswith(py_type.__name__):
            return json_type
    return "string"


# Parameters that exist for the process, not the caller. `provider` is
# generate_cover_letter's dependency-injection seam for tests; advertising it
# would invite the agent to pass one. Excluded from every tool's schema.
_INTERNAL_PARAMS = frozenset({"provider"})


def _input_schema(fn: Any) -> dict:
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
        if name in _INTERNAL_PARAMS:
            continue
        properties[name] = {"type": _json_type(param.annotation)}
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


def build_mcp_app() -> Any:
    """Build and return a Starlette ASGI app for the MCP streamable-HTTP endpoint.
    
    Returns a Starlette app that speaks JSON-RPC 2.0 and registers the nine
    agent tools with their descriptions.
    """
    server = Server(name="truthcv")

    # Register tools/list handler
    async def handle_list_tools(params: types.PaginatedRequestParams) -> types.ListToolsResult:
        """Return the list of available tools."""
        tools = [
            types.Tool(
                name=name,
                description=description,
                inputSchema=_input_schema(fn),
            )
            for name, (fn, description) in _TOOL_REGISTRY.items()
        ]
        return types.ListToolsResult(tools=tools)

    # Register tools/call handler  
    async def handle_call_tool(
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        """Call a registered tool by name."""
        if params.name not in _TOOL_REGISTRY:
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Unknown tool '{params.name}'.",
                    )
                ],
                isError=True,
            )

        fn, _ = _TOOL_REGISTRY[params.name]
        try:
            result = fn(**(params.arguments or {}))
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=str(result),
                    )
                ]
            )
        except Exception as e:
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=str(e),
                    )
                ],
                isError=True,
            )

    # The SDK validates the incoming `params` member against the type given
    # here and hands the handler the result, so these must be the *params*
    # models. Passing the whole request model (CallToolRequest) makes every
    # call fail validation with -32602 before the handler is reached.
    server.add_request_handler(
        "tools/list", types.PaginatedRequestParams, handle_list_tools
    )
    server.add_request_handler(
        "tools/call", types.CallToolRequestParams, handle_call_tool
    )

    # Build and return the streamable-HTTP ASGI app.
    # Note: streamable_http_path="/" means the JSON-RPC endpoint is at the root of
    # this sub-app, so when mounted at "/mcp" in the FastAPI app, it will be at
    # "/mcp". If we specified streamable_http_path="/mcp" here, mounting at "/mcp"
    # would result in "/mcp/mcp".
    return server.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
    )
