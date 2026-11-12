"""Gmail response-tracking workflow shared by the agent tool and the sync gate.

The opt-in gate and the applied/pending summary live here so the MCP tool in
``truthcv/adapters/mcp/tools_gmail.py`` only translates the result. The gate must match
the ``/api/gmail/*`` routes, so any change to one belongs in both.
"""

from __future__ import annotations

import truthcv.infra.secretstore as secretstore


def tracking_enabled() -> bool:
    """Whether Gmail response-tracking is configured and opted in.

    Exists so the HTTP guard, the OAuth redirect ladder, the status report and
    the MCP gate all share one predicate. Gated on the secretstore "jev" record
    (the same one Jev screening cross-checks use): a non-empty apiKey AND
    useForEmailTracking set to True. Gmail sync auto-applies Jev-confirmed
    transitions, so it must never run on a bare Gmail connection without this
    explicit opt-in.
    """
    conn = secretstore.get_connection("jev")
    return bool(conn.get("apiKey")) and conn.get("useForEmailTracking") is True


def require_tracking_enabled() -> None:
    """Raise ValueError unless Gmail response-tracking is configured and opted in.

    Exists as a service function so every caller that runs a Gmail sync gates
    the same way, not only the agent tool.

    Mirrors truthcv.adapters.http.guards.require_gmail_tracking_enabled's gate exactly: the
    secretstore "jev" connection must have a non-empty apiKey AND
    useForEmailTracking set to True. Gmail sync auto-applies Jev-confirmed
    status transitions, so it must never run without this explicit opt-in.
    """
    if not tracking_enabled():
        raise ValueError(
            "Gmail response-tracking requires a saved Jev API key and useForEmailTracking enabled."
        )


def check_responses() -> dict:
    """Run a Gmail response-tracking sync and return a structured summary.

    Exists so the agent tool gets the applied/pending diff from one place
    rather than assembling it in the adapter. Gated by require_tracking_enabled.

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
    require_tracking_enabled()
    # Deferred on purpose: callers and tests patch "truthcv.domain.gmailsync.service.run_sync"
    # and "truthcv.domain.gmailsync.store.load_suggestions" at those module paths. A module-level
    # import would bind the original functions here and silently bypass the patches.
    from truthcv.domain.gmailsync import service as gmailsync_service
    from truthcv.domain.gmailsync.store import load_suggestions

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


def complete_login(code: str | None, state: str | None, error: str | None) -> str | None:
    """Finish the Gmail OAuth callback and return the ``gmailError`` code, or None on success.

    Exists so the redirect-policy ladder lives outside the HTTP handler, which
    only turns the result into a RedirectResponse. The callback is a browser
    redirect target with nowhere to show a JSON error, so every failure is a
    code rather than an exception: ``not_enabled`` (feature gate closed
    mid-flow), Google's own ``error`` or ``missing_code`` (denied consent, no
    code/state), and ``auth_failed`` (token exchange failed).
    """
    # Looked up through the module at call time so patches on
    # truthcv.integrations.connections.auth.gmail keep intercepting.
    from truthcv.integrations.connections.auth import gmail as gmail_auth

    if not tracking_enabled():
        return "not_enabled"
    if error or not code or not state:
        return error or "missing_code"
    try:
        gmail_auth.complete_login(code, state)
    except gmail_auth.AuthError:
        return "auth_failed"
    return None


def status() -> dict:
    """Gmail connection status for the Settings page.

    Exists so the status route only shapes the response. It never refuses: it
    reports the tracking gate's own state (tracking_enabled) so the UI can
    explain why Gmail is unavailable. Keys: connected, email, reauth_required,
    tracking_enabled, refresh_expires_at (epoch seconds of the stored refresh
    token's expiry; None when the record has none or Gmail is not connected).
    """
    oauth = secretstore.get_connection("gmail").get("oauth") or {}
    return {
        "connected": bool(oauth.get("email")),
        "email": oauth.get("email") or None,
        "reauth_required": oauth.get("reauthRequired") is True,
        "tracking_enabled": tracking_enabled(),
        "refresh_expires_at": oauth.get("refreshExpiresAt"),
    }


def dismiss_and_count(ids: list[str]) -> tuple[int, int]:
    """Dismiss the given suggestions and return (dismissed, pending remaining).

    Exists so the route makes one call; the pending total is read after the
    dismissal so it reflects the new state.
    """
    from truthcv.domain.gmailsync import service as gmailsync_service

    dismissed = gmailsync_service.dismiss(ids)
    _, pending = gmailsync_service.list_pending(1, 0)
    return dismissed, pending


def accept_and_count(suggestion_id: str):
    """Accept one suggestion and return (accepted, pending remaining).

    SuggestionNotFound / SuggestionNotAcceptable from gmailsync propagate for
    the route to map to 404 / 409.
    """
    from truthcv.domain.gmailsync import service as gmailsync_service

    accepted = gmailsync_service.accept(suggestion_id)
    _, pending = gmailsync_service.list_pending(1, 0)
    return accepted, pending
