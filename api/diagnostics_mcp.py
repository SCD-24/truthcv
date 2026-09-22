"""A second, bearer-token-authenticated, strictly read-only MCP endpoint.

This module owns its own tool registry (`_DIAG_TOOL_REGISTRY`) and its own
`mcp.server.Server`, deliberately separate from `agenttools.mcp_app`'s
`_TOOL_REGISTRY`: the operational /mcp surface can start runs, record
screenings and applications, and generate cover letters, and none of that
belongs on a surface a remote MCP client can reach with nothing but a bearer
token. Every tool registered here reads a store and returns a summary; none
of them write anything, and `get_status` never returns secret material —
only a boolean for whether secret encryption is available.

The ASGI app and session manager built here are wired into `api.main`'s
route and lifespan; this module has no FastAPI route of its own.
"""

from __future__ import annotations

import hmac
import json
import os
from datetime import datetime
from email.utils import parsedate_to_datetime

from mcp import types
from mcp.server import Server
from mcp.server.transport_security import TransportSecuritySettings

import applications.store as _applications_store
import gmailsync.store as _gmailsync_store
import runs.store as _runs_store
import screening.store as _screening_store
import secretstore
from agenttools.mcp_app import _input_schema

# A diagnostics summary line only needs enough of a posting to identify it,
# not the whole body (which can run to several KB and is not itself
# diagnostic information).
_POSTING_TEXT_PREVIEW_CHARS = 280

# Bounds applied to every list_* tool's `limit` argument by _clamp_limit.
_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 200


def _clamp_limit(limit: int | None) -> int:
    """Clamp a caller-supplied list `limit` into a safe, bounded range.

    A missing or non-positive limit (None, 0, or negative) means "use the
    default" — `_DEFAULT_LIST_LIMIT` — rather than "no limit", so a remote
    MCP client can never force an unbounded page by passing 0 or -1. Any
    limit above `_MAX_LIST_LIMIT` is capped there.
    """
    if not limit or limit <= 0:
        return _DEFAULT_LIST_LIMIT
    return min(limit, _MAX_LIST_LIMIT)


def list_runs(limit: int = 50, offset: int = 0) -> dict:
    """One page of run records, newest-started first, with the total drawn from.

    `limit` is clamped by `_clamp_limit`: <=0 (or omitted) means the default
    of 50, and anything above 200 is capped there — never "all records".
    """
    records, total = _runs_store.list_page(limit=_clamp_limit(limit), offset=offset)
    return {"total": total, "runs": [r.to_dict() for r in records]}


def get_run(run_id: str) -> dict:
    """The run record with this id as a dict, or {} if none exists."""
    record = _runs_store.get(run_id)
    return record.to_dict() if record else {}


def _screening_summary(s) -> dict:
    """A read-only summary of one screening, with posting_text truncated."""
    posting_text = s.posting_text or ""
    return {
        "id": s.id,
        "company": s.company,
        "role": s.role,
        "url": s.url,
        "screened_date": s.screened_date,
        "verdict": s.verdict,
        "screening_blocker": s.screening_blocker,
        "approval": s.approval,
        "profile": s.profile,
        "run_id": s.run_id,
        "posting_text_preview": posting_text[:_POSTING_TEXT_PREVIEW_CHARS],
        "posting_text_truncated": len(posting_text) > _POSTING_TEXT_PREVIEW_CHARS,
    }


def list_screenings(limit: int = 50, offset: int = 0) -> dict:
    """A summarised page of screening records, newest-created first.

    Each entry carries only a truncated preview of `posting_text`; the full
    posting body is not diagnostic information and can be large. `limit` is
    clamped by `_clamp_limit` (default 50, cap 200; <=0 means the default).
    """
    records = sorted(
        _screening_store.load_all(),
        key=lambda s: s.created_at or (f"{s.screened_date}T00:00:00+00:00" if s.screened_date else ""),
        reverse=True,
    )
    total = len(records)
    if offset > 0:
        records = records[offset:]
    records = records[:_clamp_limit(limit)]
    return {"total": total, "screenings": [_screening_summary(s) for s in records]}


def _application_summary(a) -> dict:
    """A read-only summary of one tracked application."""
    return {
        "id": a.id,
        "company": a.company,
        "role": a.role,
        "status": a.status,
        "submitted": a.submitted,
        "submission_type": a.submission_type,
        "application_date": a.application_date,
        "profile": a.profile,
        "run_id": a.run_id,
        "screening_id": a.screening_id,
    }


def list_applications(limit: int = 50, offset: int = 0) -> dict:
    """A summarised page of tracked applications, newest-created first.

    `limit` is clamped by `_clamp_limit` (default 50, cap 200; <=0 means
    the default).
    """
    records = sorted(
        _applications_store.load_all(), key=lambda a: a.created_at, reverse=True
    )
    total = len(records)
    if offset > 0:
        records = records[offset:]
    records = records[:_clamp_limit(limit)]
    return {"total": total, "applications": [_application_summary(a) for a in records]}


def get_status() -> dict:
    """Per-store record counts and whether secret encryption is available.

    Deliberately returns no secret material — not the encryption key, not
    any stored credential — only a boolean for whether ENCRYPTION_KEY is
    currently set and usable.
    """
    return {
        "runs": len(_runs_store.load_all()),
        "screenings": len(_screening_store.load_all()),
        "applications": len(_applications_store.load_all()),
        "encryption_available": secretstore.encryption_available(),
        "gmail_suggestions": len(_gmailsync_store.load_suggestions()),
        "gmail_last_synced_at": _gmailsync_store.load_sync_state().last_synced_at,
    }


def get_gmail_sync_status() -> dict:
    """A summary of Gmail response-sync state: no message ids, just counts.

    Returns `last_synced_at` (epoch seconds, 0 if never synced) and
    `processed_message_count` (the number of processed message ids recorded,
    not the id list itself — this stays a summary, not a dump of state).
    """
    state = _gmailsync_store.load_sync_state()
    return {
        "last_synced_at": state.last_synced_at,
        "processed_message_count": len(state.processed_message_ids),
    }


def _suggestion_timestamp(s) -> float:
    """Best-effort epoch seconds for a suggestion's `date` string.

    The stored value is the raw Gmail `Date` header (RFC 2822, e.g.
    "Mon, 3 Jun 2024 09:12:00 +0200"), which sorts by weekday name if
    compared lexicographically — so parse it. ISO-8601 is accepted as a
    fallback; anything unparseable sorts as 0 (oldest).
    """
    raw = (s.date or "").strip()
    if not raw:
        return 0.0
    try:
        return parsedate_to_datetime(raw).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return 0.0


def list_gmail_suggestions(limit: int = 50, offset: int = 0) -> dict:
    """A page of Gmail response-sync suggestions, newest-first by `date`.

    Ordering parses the stored Gmail `Date` header (see
    `_suggestion_timestamp`) rather than comparing strings. `limit` is
    clamped by `_clamp_limit` (default 50, cap 200; <=0 means the
    default). `offset` is applied before the limit. Each entry is the
    suggestion's own to_dict() — snippets are already short, so nothing is
    truncated further.
    """
    records = sorted(
        _gmailsync_store.load_suggestions(), key=_suggestion_timestamp, reverse=True
    )
    total = len(records)
    if offset > 0:
        records = records[offset:]
    records = records[:_clamp_limit(limit)]
    return {"total": total, "suggestions": [s.to_dict() for s in records]}


# Exactly seven read-only tools. Nothing here writes to a store, starts a
# run, or generates a document — this registry is deliberately smaller than
# agenttools.mcp_app._TOOL_REGISTRY, not a superset of it.
_DIAG_TOOL_REGISTRY = {
    "list_runs": (
        list_runs,
        "Lists agent run records, newest-started first. Read-only. "
        "limit defaults to 50, capped at 200; limit<=0 means the default.",
    ),
    "get_run": (
        get_run,
        "Returns one run record by id, or {} if none exists. Read-only.",
    ),
    "list_screenings": (
        list_screenings,
        "Lists screening records, newest-created first, summarised with "
        "posting_text truncated to a short preview. Read-only. "
        "limit defaults to 50, capped at 200; limit<=0 means the default.",
    ),
    "list_applications": (
        list_applications,
        "Lists tracked applications, newest-created first, summarised. "
        "Read-only. limit defaults to 50, capped at 200; limit<=0 means "
        "the default.",
    ),
    "get_status": (
        get_status,
        "Returns per-store record counts and whether secret encryption is "
        "available. Never returns secret material.",
    ),
    "get_gmail_sync_status": (
        get_gmail_sync_status,
        "Returns a summary of Gmail response-sync state: last_synced_at and "
        "processed_message_count. Never returns the message id list itself. "
        "Read-only.",
    ),
    "list_gmail_suggestions": (
        list_gmail_suggestions,
        "Lists Gmail response-sync suggestions, newest-first by date. "
        "Read-only. limit defaults to 50, capped at 200; limit<=0 means "
        "the default.",
    ),
}


# Build a second MCP Server app for the diagnostics streamable-HTTP JSON-RPC
# endpoint. Mirrors the construction of the operational server in
# api/main.py: same transport security relaxation (this endpoint is reached
# over the compose network / a tunnel, not a browser, so the SDK's
# DNS-rebinding guard would otherwise 421 legitimate requests whose Host
# header isn't 127.0.0.1), same JSON-response, stateless-http streamable-HTTP
# app.
_diag_mcp_server = Server(name="truthcv-diagnostics")
_diag_mcp_http_app = _diag_mcp_server.streamable_http_app(
    # Must match the path this app is reached at — the /mcp/diagnostics route
    # in api/main.py forwards the request scope verbatim, so scope["path"] is
    # still "/mcp/diagnostics".
    streamable_http_path="/mcp/diagnostics",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
    json_response=True,
    stateless_http=True,
)


async def _handle_diag_list_tools(ctx, params) -> types.ListToolsResult:
    """Return the list of available diagnostics tools.

    The SDK dispatches request handlers as ``handler(ctx, params)``; both
    arguments are unused here because the tool list is static.
    """
    tools = [
        types.Tool(
            name=name,
            description=description,
            inputSchema=_input_schema(fn),
        )
        for name, (fn, description) in _DIAG_TOOL_REGISTRY.items()
    ]
    return types.ListToolsResult(tools=tools)


async def _handle_diag_call_tool(ctx, params) -> types.CallToolResult:
    """Call a registered diagnostics tool by name.

    The SDK dispatches request handlers as ``handler(ctx, params)``, where
    ``params`` carries the tool name and arguments.
    """
    if params.name not in _DIAG_TOOL_REGISTRY:
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=f"Unknown tool '{params.name}'.",
                )
            ],
            isError=True,
        )

    fn, _ = _DIAG_TOOL_REGISTRY[params.name]
    try:
        result = fn(**(params.arguments or {}))
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False),
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


_diag_mcp_server.add_request_handler(
    "tools/list", types.PaginatedRequestParams, _handle_diag_list_tools
)
_diag_mcp_server.add_request_handler(
    "tools/call", types.CallToolRequestParams, _handle_diag_call_tool
)


def diagnostics_token_ok(given: str) -> bool:
    """Whether `given` matches DIAGNOSTICS_MCP_TOKEN.

    Same rule as api.routes._agent_token_ok: an unset or empty secret
    matches nothing, so a deployment that never set the token cannot be
    reached by any bearer value, including an empty one.
    """
    secret = os.environ.get("DIAGNOSTICS_MCP_TOKEN", "").strip()
    if not secret:
        return False
    return hmac.compare_digest(
        given.encode("utf-8", "surrogateescape"), secret.encode("utf-8")
    )


# Exposed for api/main.py: the ASGI app to forward /mcp/diagnostics requests
# to, and the session manager whose run() must wrap the app's lifetime (see
# api/main.py's lifespan) — without it every request raises "Task group is
# not initialized".
diagnostics_mcp_app = _diag_mcp_http_app
diagnostics_session_manager = _diag_mcp_server.session_manager
