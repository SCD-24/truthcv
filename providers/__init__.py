"""Provider layer: select an LLMProvider from the resolved credentials.

The active provider and its credentials come from
secretstore.resolve_credentials (encrypted secrets.enc, falling back to
environment variables). Resolving credentials through the neutral secretstore
package — rather than api — keeps this layer a leaf that depends only downward.
Adding a new provider later is one new file + one branch here. Nothing in the
truthfulness path depends on which provider is returned.
"""

from __future__ import annotations

from .base import LLMProvider, Message, ProviderError

__all__ = ["LLMProvider", "Message", "ProviderError", "get_provider"]

_cached: LLMProvider | None = None


def get_provider(refresh: bool = False) -> LLMProvider:
    """Return the configured provider, selected by LLM_PROVIDER.

    LLM_PROVIDER=anthropic|openai|ollama (default: anthropic). Reads the matching
    credential env var. Raises ProviderError on misconfiguration.
    """
    global _cached
    if _cached is not None and not refresh:
        return _cached

    from secretstore import resolve_credentials

    creds = resolve_credentials()
    name = creds["activeProvider"].strip().lower()
    model = creds["model"] or None
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        _cached = AnthropicProvider(model=model, api_key=creds["anthropicApiKey"] or None)
    elif name == "openai":
        from .openai_provider import OpenAIProvider

        _cached = OpenAIProvider(model=model, api_key=creds["openaiApiKey"] or None)
    elif name == "ollama":
        from .ollama_provider import OllamaProvider

        _cached = OllamaProvider(model=model, host=creds["ollamaHost"] or None)
    elif name == "fake":
        from .fake import FakeProvider

        _cached = FakeProvider()
    else:
        raise ProviderError(
            f"Unknown LLM_PROVIDER '{name}'. Use anthropic, openai, or ollama."
        )
    return _cached


def reset_provider() -> None:
    """Clear the cached provider (used by tests)."""
    global _cached
    _cached = None
