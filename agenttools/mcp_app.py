"""MCP application with tool wrappers for streamable-HTTP integration.

This module builds a Starlette ASGI app that exposes the agent tool surface
as an MCP streamable-HTTP JSON-RPC endpoint.
"""

from __future__ import annotations

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


def build_mcp_app() -> Any:
    """Build and return a Starlette ASGI app for the MCP streamable-HTTP endpoint.
    
    Returns a Starlette app that speaks JSON-RPC 2.0 and registers the nine
    agent tools with their descriptions.
    """
    server = Server(name="truthcv")

    # Register tools/list handler
    async def handle_list_tools(request: types.ListToolsRequest) -> types.ListToolsResult:
        """Return the list of available tools."""
        tools = []
        for name, (fn, description) in _TOOL_REGISTRY.items():
            # Build a basic inputSchema with all parameters as optional strings
            input_schema = {
                "type": "object",
                "properties": {},
                "required": [],
            }
            tools.append(
                types.Tool(
                    name=name,
                    description=description,
                    inputSchema=input_schema,
                )
            )
        return types.ListToolsResult(tools=tools)

    # Register tools/call handler  
    async def handle_call_tool(
        request: types.CallToolRequest,
    ) -> types.CallToolResult:
        """Call a registered tool by name."""
        if request.params.name not in _TOOL_REGISTRY:
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Unknown tool '{request.params.name}'.",
                    )
                ],
                isError=True,
            )

        fn, _ = _TOOL_REGISTRY[request.params.name]
        try:
            result = fn(**request.params.arguments)
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

    server.add_request_handler("tools/list", types.ListToolsRequest, handle_list_tools)
    server.add_request_handler("tools/call", types.CallToolRequest, handle_call_tool)

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
