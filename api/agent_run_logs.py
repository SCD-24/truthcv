"""Validate bounded agent log projections without ever exposing their source strings."""

from __future__ import annotations

import asyncio
from urllib.parse import urlencode

import runs.store as _runs_store
from api.agent_diagnostics import _fetch, _integer, _safe_id, _timestamp

_MAX_EXCERPTS = 200
_SUMMARIES = {
    "precondition": "Agent precondition failed",
    "configuration": "Agent configuration failed",
    "mcp_connection": "Agent tool connection failed",
    "provider_error": "Agent provider failed",
    "fatal": "Agent failed",
    "harness_exit": "Agent harness exited",
    "harness_error": "Agent error",
    "provider_http": "Provider HTTP error",
    "provider_network": "Provider network error",
    "loop_event": "Agent loop event",
    "done": "Agent run ended",
    "tool_failure": "Agent tool failed",
}
_PROVIDERS = {"anthropic", "openai", "openai_responses", "openrouter", "ollama"}
_LOOP_KINDS = {"compaction", "retry", "reflection", "emptyTurn", "turnCapReached", "wrapUp", "stop"}
_STOP_REASONS = {"toolCalls", "end", "length", "error", "aborted", "turnCapReached"}
_BASE_KEYS = {"schema_version", "run_id", "availability", "reason", "excerpts",
              "next_before_offset", "truncated", "omitted"}
_EXCERPT_KEYS = {"offset", "observed_at", "category", "summary"}
_OPTIONAL = {
    "harness_exit": {"exit_code"},
    "harness_error": {"retryable", "retry_after_ms"},
    "provider_http": {"retryable", "retry_after_ms"},
    "provider_network": {"retryable", "retry_after_ms"},
    "loop_event": {"turn"},
    "done": {"stop_reason", "turns", "exit_code"},
}
_REQUIRED = {
    "harness_exit": {"exit_code"}, "provider_http": {"provider", "http_status"},
    "provider_network": {"provider"}, "loop_event": {"kind"},
}


def _excerpt(item) -> bool:
    if not isinstance(item, dict) or not isinstance(item.get("category"), str):
        return False
    category = item["category"]
    if (category not in _SUMMARIES or not _EXCERPT_KEYS | _REQUIRED.get(category, set()) <= item.keys()
            or not item.keys() <= _EXCERPT_KEYS | _REQUIRED.get(category, set()) | _OPTIONAL.get(category, set())
            or item["summary"] != _SUMMARIES[category] or not _integer(item["offset"])
            or not _timestamp(item["observed_at"])):
        return False
    return (('provider' not in item or type(item['provider']) is str and item['provider'] in _PROVIDERS)
            and ('http_status' not in item or _integer(item['http_status'], 100) and item['http_status'] <= 599)
            and ('retryable' not in item or type(item['retryable']) is bool)
            and ('retry_after_ms' not in item or _integer(item['retry_after_ms']) and item['retry_after_ms'] <= 3_600_000)
            and ('kind' not in item or type(item['kind']) is str and item['kind'] in _LOOP_KINDS)
            and ('stop_reason' not in item or type(item['stop_reason']) is str and item['stop_reason'] in _STOP_REASONS)
            and all(key not in item or _integer(item[key]) and item[key] <= 1_000_000 for key in ('turn', 'turns'))
            and ('exit_code' not in item or _integer(item['exit_code']) and item['exit_code'] <= 255))


def _page(data, run_id: str, limit: int, before: int | None) -> bool:
    if not isinstance(data, dict) or set(data) != _BASE_KEYS:
        return False
    excerpts, cursor = data['excerpts'], data['next_before_offset']
    if (type(data['schema_version']) is not int or data['schema_version'] != 1
            or type(data['run_id']) is not str or data['run_id'] != run_id
            or type(data['availability']) is not str or data['availability'] not in ('available', 'unavailable')
            or type(data['truncated']) is not bool or type(data['omitted']) is not bool
            or not isinstance(excerpts, list) or len(excerpts) > limit
            or cursor is not None and not _integer(cursor, 1)):
        return False
    if data['availability'] == 'unavailable':
        return (type(data['reason']) is str and data['reason'] in ('missing', 'unreadable')
                and not excerpts and cursor is None and data['truncated'] is False and data['omitted'] is False)
    if (data['reason'] is not None or data['truncated'] != (cursor is not None)
            or cursor is not None and before is not None and cursor >= before
            or not all(_excerpt(item) for item in excerpts)):
        return False
    offsets = [item['offset'] for item in excerpts]
    return (all(a > b for a, b in zip(offsets, offsets[1:]))
            and (before is None or all(offset < before for offset in offsets))
            and (cursor is None or not offsets or cursor <= offsets[-1])
            and len({item['observed_at'] for item in excerpts}) <= 1)


def _clean(data: dict, reachability: str) -> dict:
    """Construct summaries locally rather than echoing even validated upstream text."""
    return {key: value for key, value in data.items() if key != 'excerpts'} | {
        'excerpts': [{**{key: value for key, value in item.items() if key != 'summary'},
                      'summary': _SUMMARIES[item['category']]} for item in data['excerpts']],
        'reachability': reachability,
    }


async def get_run_logs(run_id: str, limit: int = 50, before_offset: int | None = None) -> dict:
    """Read only classified log excerpts for a retained run, never raw log text."""
    safe_id = _safe_id(run_id)
    base = {"schema_version": 1, "run_id": run_id if safe_id else None,
            "availability": "unavailable", "excerpts": [], "next_before_offset": None,
            "truncated": False, "omitted": False, "reachability": "unknown"}

    def unavailable(reason: str, reachability: str = "unknown") -> dict:
        return {**base, "reason": reason, "reachability": reachability}

    if (not safe_id or not _integer(limit, 1) or limit > _MAX_EXCERPTS
            or before_offset is not None and not _integer(before_offset, 1)):
        return unavailable("invalid_request")
    if await asyncio.to_thread(_runs_store.get, run_id) is None:
        return unavailable("unknown_run")
    query = {'limit': limit, **({'before_offset': before_offset} if before_offset is not None else {})}
    data, reason, reachability = await asyncio.to_thread(
        _fetch, f"/diagnostics/runs/{run_id}/logs?{urlencode(query)}")
    if reason is not None:
        return unavailable(reason, reachability)
    try:
        valid = _page(data, run_id, limit, before_offset)
    except (TypeError, ValueError):
        valid = False
    if not valid:
        return unavailable("malformed_response", reachability)
    if data['availability'] == 'unavailable':
        return unavailable(data['reason'], reachability)
    return _clean(data, reachability)
