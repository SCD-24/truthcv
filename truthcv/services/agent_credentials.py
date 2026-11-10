"""LLM credentials for the unattended agent: per-card resolution, the forced
subscription-token refresh, and the per-stage route credentials.

Framework-free: failures raise services.errors (NotFound → 404, Unavailable →
503) with the same detail text the HTTP routes always returned. Credentials
are returned as the camelCase wire dict (the ``AgentLlmCredentials`` aliases)
so the stage-routes response can carry them unchanged. Tokens are
response-only and never logged.

``get_valid_access_token`` and ``_CARD_CREDENTIALS`` are module globals read
at call time, so tests can patch them on this module.
"""

from __future__ import annotations

import truthcv.integrations.modelrouting as modelrouting
import truthcv.infra.secretstore as secretstore
from truthcv.integrations.connections.auth import codex as codex_auth
from truthcv.integrations.connections.auth.claude import AuthError, get_valid_access_token
from truthcv.integrations.providers import OPENROUTER_BASE_URL
from truthcv.services.errors import NotFound, ServiceError, Unavailable


def _credentials(
    auth_type: str, token: str, model: str, provider: str, wire: str, base_url: str = ""
) -> dict:
    """The camelCase wire shape, every field present, in the model's field order."""
    return {
        "authType": auth_type,
        "token": token,
        "model": model,
        "baseUrl": base_url,
        "provider": provider,
        "wire": wire,
    }


def _claude_credentials(model: str) -> dict:
    """Resolve claude card credentials: oauth first, then apikey, else 404/503."""
    conn = secretstore.get_connection("claude")
    oauth = conn.get("oauth") or {}
    if oauth.get("accessToken") and conn.get("authMode") != "apikey":
        try:
            token = get_valid_access_token()
        except AuthError:
            raise Unavailable("Claude subscription needs reconnecting.") from None
        return _credentials("oauth", token, model, "claude", "anthropic-messages")

    api_key = conn.get("apiKey")
    if api_key:
        return _credentials("api_key", api_key, model, "claude", "anthropic-messages")
    raise NotFound("Not Found")


def _codex_credentials(model: str) -> dict:
    """Resolve codex card credentials: subscription oauth or apikey, OpenAI wire."""
    conn = secretstore.get_connection("codex")
    oauth = conn.get("oauth") or {}
    if oauth.get("accessToken") and conn.get("authMode") != "apikey":
        try:
            token = codex_auth.get_valid_access_token()
        except codex_auth.AuthError:
            raise Unavailable("ChatGPT subscription needs reconnecting.") from None
        return _credentials("oauth", token, model, "codex", "openai-responses")
    api_key = conn.get("apiKey")
    if not api_key:
        raise NotFound("Not Found")
    return _credentials("api_key", api_key, model, "codex", "openai-chat-completions")


def _openrouter_credentials(model: str) -> dict:
    """Resolve openrouter card credentials: apikey-only, plain OpenAI wire (not
    the Anthropic-compat shim, which is only for the claude CLI)."""
    api_key = secretstore.get_connection("openrouter").get("apiKey")
    if not api_key:
        raise NotFound("Not Found")
    return _credentials(
        "api_key", api_key, model, "openrouter", "openai-chat-completions",
        base_url=OPENROUTER_BASE_URL,
    )


def _ollama_credentials(model: str) -> dict:
    """Resolve ollama card credentials: url-only, no token, OpenAI-shaped wire."""
    base_url = secretstore.get_connection("ollama").get("baseUrl")
    if not base_url:
        raise NotFound("Not Found")
    return _credentials(
        "url", "", model, "ollama", "openai-chat-completions", base_url=base_url
    )


_CARD_CREDENTIALS = {
    "claude": _claude_credentials,
    "codex": _codex_credentials,
    "openrouter": _openrouter_credentials,
    "ollama": _ollama_credentials,
}


def credentials_for_route(route: modelrouting.Route | None) -> dict:
    """Credentials for a route (None = the claude card, default model).
    Raises NotFound when the card is unknown or has no usable credentials.

    Public so the llm-credentials handler and ``stage_routes`` share one
    card lookup."""
    card = route.connection if route else "claude"
    model = route.model if route else ""
    resolve = _CARD_CREDENTIALS.get(card)
    if resolve is None:
        raise NotFound("Not Found")
    return resolve(model)


_REFRESH_PROVIDERS = {
    "claude": (
        lambda **kw: get_valid_access_token(**kw), AuthError, "Claude subscription needs reconnecting."),
    "codex": (
        lambda **kw: codex_auth.get_valid_access_token(**kw),
        codex_auth.AuthError,
        "ChatGPT subscription needs reconnecting.",
    ),
}


def refresh_token(provider: str, rejected_sha256: str) -> str:
    """Force a fresh subscription token after the caller saw ``rejected_sha256``
    rejected. NotFound when the card has no oauth token or is in apikey mode;
    Unavailable when reconnecting is needed.

    Exists so the refresh rule lives outside the HTTP handler, which keeps only
    the agent-token guard."""
    conn = secretstore.get_connection(provider)
    if not (conn.get("oauth") or {}).get("accessToken") or conn.get("authMode") == "apikey":
        raise NotFound("Not Found")
    fetch, auth_error, detail = _REFRESH_PROVIDERS[provider]
    try:
        return fetch(rejected_sha256=rejected_sha256)
    except auth_error:
        raise Unavailable(detail) from None


def _stage_credentials(route) -> dict | None:
    """One stage's credentials, or None when it has no route or no usable card."""
    if route is None:
        return None
    # One stage whose card has no usable credentials must not blank the
    # others: it resolves to null and the harness falls back per stages.ts.
    try:
        return credentials_for_route(route)
    except ServiceError:
        return None


def stage_routes() -> dict:
    """Credentials for the apply route and each agent stage. A stage with no
    route resolves to null.

    Exists so the llm-routes handler keeps only the agent-token guard."""
    r = modelrouting.load()
    stages = {"apply": _stage_credentials(r.agent)}
    for name in modelrouting.AGENT_STAGE_NAMES:
        stages[name] = _stage_credentials(modelrouting.resolve_agent_stage(r, name))
    return {"stages": stages}
