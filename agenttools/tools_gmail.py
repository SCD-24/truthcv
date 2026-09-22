"""MCP tool for triggering a Gmail response-tracking sync."""

from __future__ import annotations

import secretstore


def _require_gmail_tracking_enabled() -> None:
    """Raise ValueError unless Gmail response-tracking is configured and opted in.

    Mirrors api.routes.require_gmail_tracking_enabled's gate exactly: the
    secretstore "jev" connection must have a non-empty apiKey AND
    useForEmailTracking set to True. Gmail sync auto-applies Jev-confirmed
    status transitions, so it must never run without this explicit opt-in.
    """
    conn = secretstore.get_connection("jev")
    if not conn.get("apiKey") or conn.get("useForEmailTracking") is not True:
        raise ValueError(
            "Gmail response-tracking requires a saved Jev API key and useForEmailTracking enabled."
        )


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
    _require_gmail_tracking_enabled()
    from gmailsync import service as gmailsync_service
    from gmailsync.store import load_suggestions

    applied_before = {item.id for item in load_suggestions() if item.state == "applied"}
    summary = gmailsync_service.run_sync()
    suggestions = load_suggestions()
    applied_this_sync = sum(
        1 for item in suggestions if item.state == "applied" and item.id not in applied_before
    )
    pending = sum(1 for item in suggestions if item.state == "pending")
    return {
        "skipped": summary.get("skipped", False),
        "processed": summary.get("processed", 0),
        "applied": applied_this_sync,
        "pending": pending,
    }
