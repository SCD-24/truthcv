"""Wizard REST routes wired to the backend modules.

The one hard rule lives in /api/render: the guardrail runs BEFORE any file is
produced, and if it fails nothing is rendered — the response is blocked=true with
the unverifiable tokens.
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from providers import ProviderError
import services.gmail as gmail_service
from api import guards
import services.connections as connections_service

import secretstore
from connections import catalog
from connections.auth import gmail as gmail_auth
from providers import build_connection_provider

from .agent_routes import router as agent_router
from .application_routes import router as application_router
from .browser_routes import router as browser_router
from .company_finding_routes import router as company_finding_router
from .cv_routes import router as cv_router
from .job_board_routes import router as job_board_router
from .run_routes import router as run_router
from .screening_routes import router as screening_router
from .settings_routes import router as settings_router
from .truth_routes import router as truth_router
from .route_support import (
    _models_result,
)
from .schemas import (
    ApiKeyRequest,
    CompleteLoginRequest,
    ConnectionList,
    ConnectionStatus,
    ConnectionTestRequest,
    GmailStatusModel,
    GmailSyncRequest,
    ModelList,
    PollLoginResult,
    StartLoginResult,
    TestResult,
)

router = APIRouter(prefix="/api")

logger = logging.getLogger(__name__)


router.include_router(screening_router)
router.include_router(run_router)
router.include_router(company_finding_router)
router.include_router(truth_router)
router.include_router(cv_router)
router.include_router(application_router)
router.include_router(job_board_router)
router.include_router(settings_router)


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
    from gmailsync import service as gmailsync_service

    force = body.force if body is not None else False
    return gmailsync_service.run_sync(force=force)


router.include_router(agent_router)
router.include_router(browser_router)


def _connection_status(card_key: str) -> ConnectionStatus:
    meta = catalog.card(card_key)
    conn = secretstore.get_connection(card_key)
    oauth = conn.get("oauth") or {}
    has_key = bool(conn.get("apiKey")) or (card_key == "ollama" and bool(conn.get("baseUrl")))
    return ConnectionStatus(
        provider=card_key,
        label=meta["label"],
        modes=list(meta["modes"]),
        subscription_connected=bool(oauth.get("accessToken")),
        api_key_connected=has_key,
        auth_mode=conn.get("authMode", ""),
        expires_at=oauth.get("expiresAt"),
        connected_at=oauth.get("connectedAt"),
    )


@router.get("/auth/status", response_model=ConnectionList)
def get_connection_status() -> ConnectionList:
    return ConnectionList(
        encryption_available=secretstore.encryption_available(),
        connections=[_connection_status(key) for key in catalog.card_keys()],
    )


@router.post("/auth/{provider}/start", response_model=StartLoginResult)
def start_connection_login(provider: str) -> StartLoginResult:
    return StartLoginResult.model_validate(connections_service.start_login(provider))


# Specific route must come BEFORE the generic /{provider}/complete to avoid
# FastAPI matching /api/auth/claude/complete against the general pattern.
@router.post("/auth/claude/complete", response_model=ConnectionStatus)
def complete_claude_login_alias(body: CompleteLoginRequest) -> ConnectionStatus:
    """Deprecated: delegates to the generic /complete handler. Retained so a
    deployed web bundle from before this change does not break mid-deploy."""
    return _complete_login("claude", body)


@router.post("/auth/{provider}/complete", response_model=ConnectionStatus)
def _complete_login(provider: str, body: CompleteLoginRequest) -> ConnectionStatus:
    connections_service.complete_login(provider, body.code)
    return _connection_status(provider)


@router.post("/auth/{provider}/poll", response_model=PollLoginResult)
def _poll_login(provider: str) -> PollLoginResult:
    result = connections_service.poll_login(provider)
    if result.get("status") == "complete":
        return PollLoginResult(
            status="complete",
            connected_at=result.get("connectedAt"),
            expires_at=result.get("expiresAt"),
            scope=result.get("scope"),
        )
    return PollLoginResult(
        status="pending",
        interval_seconds=result.get("intervalSeconds"),
    )


@router.post("/auth/{provider}/key", response_model=ModelList)
def post_connection_key(provider: str, body: ApiKeyRequest) -> ModelList:
    models = connections_service.save_key(provider, body.api_key, body.base_url, body.bearer)
    return _models_result(models, provider)


@router.get("/auth/{provider}/models", response_model=ModelList)
def get_connection_models(provider: str) -> ModelList:
    connections_service.require_card(provider)
    try:
        models = build_connection_provider(provider, None).list_models()
    except ProviderError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 — surface upstream LLM/SDK errors cleanly
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}") from e
    return _models_result(models, provider)


@router.post("/auth/{provider}/test", response_model=TestResult)
def test_connection(provider: str, body: ConnectionTestRequest) -> TestResult:
    connections_service.require_card(provider)
    try:
        provider_obj = build_connection_provider(provider, body.model)
        provider_obj.complete("ping", [{"role": "user", "content": "ping"}])
        return TestResult(ok=True, detail="Connection succeeded.")
    except HTTPException as e:
        return TestResult(ok=False, detail=str(e.detail))
    except Exception as e:  # noqa: BLE001
        return TestResult(ok=False, detail=f"{type(e).__name__}: {e}")


@router.post("/auth/{provider}/logout", response_model=ConnectionStatus)
def logout_connection(provider: str, mode: str | None = None) -> ConnectionStatus:
    """Disconnect `provider`, defaulting to the card's currently active mode.

    Without an explicit `mode`, we clear whichever mode is currently active
    (oauth or apikey), so the card no longer reports a connection in either
    mode. Passing `mode` clears just that mode and leaves the other intact —
    that is the same semantics the existing per-mode logout tests pin.
    """
    connections_service.logout(provider, mode)
    return _connection_status(provider)
