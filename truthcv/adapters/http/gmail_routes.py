"""Gmail routes: the OAuth start/callback, connection status and response sync."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

import truthcv.services.gmail as gmail_service
from truthcv.adapters.http import guards
from truthcv.integrations.connections.auth import gmail as gmail_auth

from .schemas import (
    GmailStatusModel,
    GmailSyncRequest,
    StartLoginResult,
)

router = APIRouter()


@router.post("/auth/gmail/start", response_model=StartLoginResult)
def start_gmail_login(request: Request) -> StartLoginResult:
    """Begin the Gmail OAuth flow. Gated on the useForEmailTracking opt-in."""
    guards.require_gmail_tracking_enabled()
    redirect_uri = gmail_auth.redirect_uri_override() or str(request.url_for("gmail_callback"))
    try:
        return StartLoginResult.model_validate(gmail_auth.start_login(redirect_uri))
    except gmail_auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/auth/gmail/callback", name="gmail_callback")
def complete_gmail_login(
    code: str | None = None, state: str | None = None, error: str | None = None
) -> RedirectResponse:
    """Complete the Gmail OAuth flow, then redirect back to the app root.

    Gated the same as /start: a request reaching here without the feature
    enabled 403s rather than silently completing a login the operator can't
    use yet.

    Unlike a JSON API route, this one is a browser redirect target: there is
    nowhere for a JSON error page to be seen. Google's own denied-consent
    redirect (`?error=access_denied`, with no `code`/`state`) and a failed
    token exchange are therefore never raised as HTTP errors — both redirect
    back to the app root with a `gmailError` query param instead of the
    normal success redirect, so `code`/`state` are optional here. The same
    goes for the feature gate: closed mid-flow (key cleared or the toggle
    turned off while the consent screen was open), it redirects with
    `gmailError=not_enabled` rather than rendering a 403 JSON body.
    """
    code_error = gmail_service.complete_login(code, state, error)
    if code_error:
        query = urlencode({"gmailError": code_error})
        return RedirectResponse(url=f"/?{query}")
    return RedirectResponse(url="/")


@router.get("/gmail/status", response_model=GmailStatusModel)
def get_gmail_status() -> GmailStatusModel:
    """Gmail connection status for the Settings page.

    Unlike /auth/gmail/start and /callback, this route never 403s: it
    reports the useForEmailTracking gate's own state (tracking_enabled) so
    the UI can explain why Gmail is unavailable, rather than getting a
    blanket error.
    """
    return GmailStatusModel(**gmail_service.status())


@router.post("/gmail/responses/sync")
def sync_gmail_responses(body: GmailSyncRequest | None = None) -> dict:
    """Trigger a Gmail response-tracking sync. Gated the same as the OAuth
    routes: requires a saved Jev key and useForEmailTracking enabled.

    Returns gmailsync.service.run_sync's own summary dict unchanged.
    """
    guards.require_gmail_tracking_enabled()
    from truthcv.domain.gmailsync import service as gmailsync_service

    force = body.force if body is not None else False
    return gmailsync_service.run_sync(force=force)
