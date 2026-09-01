"""Provider layer: select an LLMProvider from the resolved credentials.

The active provider and its credentials come from modelrouting (task -> connection
+ model) and secretstore (connection -> credentials, with a legacy env/secrets
fallback for installs with no routing configured). Resolving through these neutral
packages — rather than api — keeps this layer a leaf that depends only downward.
Adding a new provider later is one new file + one branch here. Nothing in the
truthfulness path depends on which provider is returned.
"""

from __future__ import annotations

from .base import LLMProvider, Message, ProviderError

__all__ = [
    "LLMProvider", "Message", "ProviderError",
    "build_connection_provider", "get_provider", "reset_provider",
]

_cache: dict[tuple[str, str | None, str, str], LLMProvider] = {}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# The same host, one path segment shorter, and deliberately so. The OpenAI SDK
# is given a base that already includes /v1 and appends "/chat/completions";
# the claude CLI is given ANTHROPIC_BASE_URL and appends "/v1/messages" itself,
# so handing it the /v1 form yields .../api/v1/v1/messages and every request
# fails. Do not "fix" these to match.
ANTHROPIC_COMPAT_OPENROUTER_BASE_URL = "https://openrouter.ai/api"


def build_connection_provider(
    card: str, model: str | None, effort: str | None = None
) -> LLMProvider:
    """Build (uncached) a provider for a connection card. Raises ProviderError.

    *effort* is an optional effort level (e.g. ``"high"``) forwarded to the
    provider so it can configure extended-thinking or reasoning parameters.
    Pass ``None`` (the default) to leave the provider at its baseline behaviour.
    """
    from secretstore import get_connection

    conn = get_connection(card)
    if card == "claude":
        from .anthropic_provider import AnthropicProvider

        if conn.get("oauth") and conn.get("authMode") != "apikey":
            return AnthropicProvider(model=model, oauth=True, effort=effort)
        return AnthropicProvider(model=model, api_key=conn.get("apiKey") or None, effort=effort)
    if card == "codex":
        from .openai_provider import OpenAIProvider

        if conn.get("oauth") and conn.get("authMode") != "apikey":
            from connections.auth import codex as codex_auth

            token = codex_auth.get_valid_access_token()
            return OpenAIProvider(model=model, oauth_token=token, effort=effort)
        return OpenAIProvider(model=model, api_key=conn.get("apiKey") or None, effort=effort)
    if card == "openrouter":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(
            model=model, api_key=conn.get("apiKey") or None,
            base_url=OPENROUTER_BASE_URL, effort=effort,
        )
    if card == "ollama":
        from .ollama_provider import OllamaProvider

        return OllamaProvider(
            model=model, host=conn.get("baseUrl") or None,
            bearer=conn.get("bearer") or None, effort=effort,
        )
    raise ProviderError(f"Unknown connection '{card}'.")


def get_provider(task: str | None = None, refresh: bool = False) -> LLMProvider:
    """Provider for a task via the routing ladder: task route -> default ->
    legacy env behavior. LLM_PROVIDER=fake short-circuits (tests)."""
    import os

    if os.environ.get("LLM_PROVIDER", "").strip().lower() == "fake":
        from .fake import FakeProvider

        return FakeProvider()

    import modelrouting

    route = modelrouting.resolve(modelrouting.load(), task)
    if route is not None:
        card, model = route.connection, (route.model or None)
        effort: str | None = route.effort or None
    else:
        from secretstore import legacy_default

        card, model_str = legacy_default()
        model = model_str or None
        effort = None
        if card is None:
            raise ProviderError(
                "No model routing configured and LLM_PROVIDER is not one of "
                "anthropic, openai, ollama."
            )

    # Cache key includes auth mode so switching between subscription and apikey
    # returns a fresh provider with the new credential. The token's expiry is
    # not in the key because reset_provider() is the mechanism for picking up
    # a refreshed OAuth token — the provider instance captures its credential
    # at construction.
    from secretstore import get_connection

    auth_mode = get_connection(card).get("authMode", "")
    key = (card, model, effort or "", auth_mode)
    if refresh:
        _cache.pop(key, None)
    if key not in _cache:
        _cache[key] = build_connection_provider(card, model, effort)
    return _cache[key]


def reset_provider() -> None:
    """Clear all cached providers (called after settings writes and by tests)."""
    _cache.clear()
