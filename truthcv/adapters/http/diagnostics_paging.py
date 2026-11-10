"""Shared list-paging bounds for the read-only diagnostics MCP tools."""

from __future__ import annotations

# Bounds applied to every list_* tool's `limit` argument by _clamp_limit.
_DEFAULT_LIST_LIMIT = 20
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
