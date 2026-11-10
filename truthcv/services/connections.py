"""Connection (provider credential) logic moved out of the route handlers.

Lives in services so the sign-in, key-save and logout flows do not need the
API layer; it raises ``services.errors`` types instead of ``HTTPException``
and the global handler maps them back to the same statuses and detail text.
"""

from __future__ import annotations

from dataclasses import dataclass

import truthcv.integrations.providers as _providers
import truthcv.infra.secretstore as secretstore
from truthcv.integrations.connections import catalog
from truthcv.integrations.connections.auth import claude as claude_auth
from truthcv.integrations.connections.auth import codex as codex_auth
from truthcv.integrations.providers import OPENROUTER_BASE_URL, ProviderError
from truthcv.services.errors import BadRequest, NotFound

# Card -> auth module registry
_AUTH_MODULES = {"claude": claude_auth, "codex": codex_auth}
_AUTH_ERRORS = (claude_auth.AuthError, codex_auth.AuthError)


@dataclass(frozen=True)
class KeyInput:
    """The credential fields submitted with a key save, handed to probe_key."""

    api_key: str | None = None
    base_url: str | None = None
    bearer: str | None = None


def require_card(provider: str) -> dict:
    """Return the catalog card for `provider`, or raise NotFound (404).

    Exists so every connection operation rejects an unknown provider with the
    same message before touching the secret store.
    """
    try:
        return catalog.card(provider)
    except KeyError:
        raise NotFound(f"Unknown connection '{provider}'.") from None


def start_login(provider: str) -> dict:
    """Begin a subscription sign-in and return the auth module's raw result.

    Exists to keep the card check and the "which cards support subscription
    sign-in" gate out of the handler. NotFound for an unknown card,
    BadRequest when the card has no auth module or the module refuses.
    """
    require_card(provider)
    if provider not in _AUTH_MODULES:
        raise BadRequest(f"Subscription sign-in is not available for '{provider}'.")
    try:
        return _AUTH_MODULES[provider].start_login()
    except _AUTH_ERRORS as e:
        raise BadRequest(str(e)) from e


def complete_login(provider: str, code: str) -> None:
    """Finish a subscription sign-in with the pasted `code` and reset the provider.

    Exists so the exchange and the cached-provider reset stay together: a new
    credential must never be served by a provider built from the old one.
    """
    if provider not in _AUTH_MODULES:
        raise NotFound(f"Unknown connection '{provider}'.")
    try:
        _AUTH_MODULES[provider].complete_login(code)
    except _AUTH_ERRORS as e:
        raise BadRequest(str(e)) from e
    _providers.reset_provider()


def poll_login(provider: str) -> dict:
    """Poll a device-style sign-in and return the auth module's raw result.

    Exists to hold the capability check: only modules that define
    ``poll_login`` support polling.
    """
    if provider not in _AUTH_MODULES:
        raise NotFound(f"Unknown connection '{provider}'.")
    mod = _AUTH_MODULES[provider]
    if not hasattr(mod, "poll_login"):
        raise BadRequest(f"Provider '{provider}' does not support polling.")
    try:
        return mod.poll_login()
    except _AUTH_ERRORS as e:
        raise BadRequest(str(e)) from e


def probe_key(card: str, body: KeyInput) -> list[dict]:
    """Construct a provider directly from the submitted credential (never via
    the stored oauth path) and list its models. An empty submitted value falls
    back to the currently stored credential, so a bare re-validate still works."""
    conn = secretstore.get_connection(card)
    if card == "claude":
        from truthcv.integrations.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(api_key=body.api_key or conn.get("apiKey") or None)
    elif card in ("codex", "openrouter"):
        from truthcv.integrations.providers.openai_provider import OpenAIProvider

        base_url = OPENROUTER_BASE_URL if card == "openrouter" else None
        provider = OpenAIProvider(
            api_key=body.api_key or conn.get("apiKey") or None, base_url=base_url
        )
    elif card == "ollama":
        from truthcv.integrations.providers.ollama_provider import OllamaProvider

        provider = OllamaProvider(
            host=body.base_url or conn.get("baseUrl") or None,
            bearer=body.bearer or conn.get("bearer") or None,
        )
    else:
        raise ProviderError(f"Unknown connection '{card}'.")
    return provider.list_models()


def save_key(
    provider: str, api_key: str | None, base_url: str | None, bearer: str | None
) -> list[dict]:
    """Validate a submitted credential, store what was sent, and return the models.

    Exists so the probe-before-store order is enforced in one place: nothing is
    written unless the probe succeeds. A bare re-validate (nothing submitted)
    stores nothing and leaves authMode alone; submitting an api key on a card
    that also supports subscription flips authMode to "apikey".
    """
    require_card(provider)
    if not secretstore.encryption_available():
        raise BadRequest("Set ENCRYPTION_KEY in .env first.")
    try:
        models = probe_key(provider, KeyInput(api_key, base_url, bearer))
    except ProviderError as e:
        raise BadRequest(str(e)) from e
    except Exception as e:  # noqa: BLE001 — surface upstream SDK auth errors as 400s
        raise BadRequest(f"{type(e).__name__}: {e}") from e
    updates: dict = {}
    if api_key:
        updates["apiKey"] = api_key
    if base_url:
        updates["baseUrl"] = base_url
    if bearer:
        updates["bearer"] = bearer
    if api_key and "subscription" in catalog.card(provider)["modes"]:
        updates["authMode"] = "apikey"
    if updates:
        secretstore.set_connection(provider, updates)
    _providers.reset_provider()
    return models


def logout(provider: str, mode: str | None = None) -> None:
    """Disconnect `provider`, defaulting to the card's currently active mode.

    Without an explicit `mode`, we clear whichever mode is currently active
    (oauth or apikey), so the card no longer reports a connection in either
    mode. Passing `mode` clears just that mode and leaves the other intact —
    that is the same semantics the existing per-mode logout tests pin.
    """
    require_card(provider)
    if mode is not None:
        secretstore.clear_mode(provider, mode)
    else:
        conn = secretstore.get_connection(provider)
        # Pick the mode that is actually active: subscription if oauth is set,
        # otherwise apikey. clear_mode is a no-op on the missing side.
        active = "subscription" if conn.get("oauth", {}).get("accessToken") else "apikey"
        secretstore.clear_mode(provider, active)
    _providers.reset_provider()
