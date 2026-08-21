"""The agent tool surface: a registry of in-process tools plus their HTTP surfaces.

This runs in-process inside the TruthCV container using the MCP SDK (>=1.9).
REST routes GET /mcp/tools and POST /mcp/tools/{name} provide the tool surface
to non-MCP clients. The JSON-RPC endpoint (registered via mcp_app.py) exposes
the same tools via the streamable-HTTP MCP transport at POST /mcp for the agent's
Claude Code CLI invocation. It is per-application: every tool takes its state as
arguments and returns it in its result, so no tool reads or writes global state.
Critically: no tool accepts approval-related parameters; the tools/list endpoint
(both REST and JSON-RPC) exposes every tool's parameters so that guarantee can be
verified from the outside.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from agenttools.tools_letter import generate_cover_letter
from agenttools.tools_ledger import (
    check_cooldown,
    get_canonical_cv,
    get_job_profiles,
    get_profile_answers,
    record_application,
    record_screening,
    recommend_salary,
)
from agenttools.tools_boards import record_company_board

TOOLS: dict[str, Callable[..., dict]] = {}


def register(name: str, fn: Callable[..., dict]) -> None:
    """Add `fn` to the tool registry under `name`."""
    TOOLS[name] = fn


def tool_names() -> list[str]:
    """Every registered tool name."""
    return list(TOOLS)


register("generate_cover_letter", generate_cover_letter)
register("record_application", record_application)
register("record_screening", record_screening)
register("check_cooldown", check_cooldown)
register("get_canonical_cv", get_canonical_cv)
register("get_profile_answers", get_profile_answers)
register("record_company_board", record_company_board)
register("get_job_profiles", get_job_profiles)
register("recommend_salary", recommend_salary)

router = APIRouter(prefix="/mcp")


def _tool_params(fn: Callable[..., dict]) -> list[str]:
    """The parameter names of a registered tool, in declaration order."""
    return list(inspect.signature(fn).parameters)


@router.get("/tools")
def list_tools() -> dict[str, list[dict[str, Any]]]:
    """Every registered tool with its parameter names."""
    tools = [{"name": name, "params": _tool_params(fn)} for name, fn in TOOLS.items()]
    return {"tools": tools}


@router.post("/tools/{name}")
def call_tool(name: str, body: dict[str, Any]) -> dict:
    """Invoke a registered tool by name with `body` as its keyword arguments."""
    fn = TOOLS.get(name)
    if fn is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{name}'.")
    try:
        return fn(**body)
    except TypeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
