"""MCP tool for triggering a Gmail response-tracking sync."""

from __future__ import annotations

from services.gmail import check_responses


def check_gmail_responses() -> dict:
    """Run a Gmail response-tracking sync and return a structured summary.

    Gated the same as the /api/gmail/* routes: requires a saved Jev API key
    and useForEmailTracking enabled on the "jev" connection. Raises
    ValueError, surfaced to the caller as a tool error, when the gate is
    closed.

    `applied` is computed by diffing the suggestion store's "applied" ids
    before and after this sync, so it reports transitions from THIS call
    only, not the lifetime total sitting in the store. `pending` is not
    diffed — it is the current count of suggestions in state "pending" at
    the end of this call, i.e. the operator's present review queue, not a
    per-sync delta. `skipped` and `processed` are run_sync's own summary
    fields passed through unchanged.

    Returns:
        Dict with skipped (True when the sync was throttled and did nothing
        this call), processed (messages processed THIS sync, 0 when
        skipped), applied (status transitions auto-applied by THIS sync from
        Jev-confirmed employer replies), and pending (current count of
        suggestions awaiting operator review).
    """
    return check_responses()
