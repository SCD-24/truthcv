"""OpenAIProvider.list_models: the chat-family narrowing is OpenAI-only.

OpenRouter reuses the OpenAI client with a different base_url, but namespaces
every model id as vendor/model, so applying OpenAI's id filter to it returns
nothing and empties the model picker.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from providers.openai_provider import OpenAIProvider

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _provider(monkeypatch: pytest.MonkeyPatch, ids: list[str], base_url: str | None):
    provider = OpenAIProvider(api_key="k", base_url=base_url)
    listing = SimpleNamespace(data=[SimpleNamespace(id=i) for i in ids])
    monkeypatch.setattr(
        provider._client, "models", SimpleNamespace(list=lambda: listing)
    )
    return provider


def test_openrouter_keeps_namespaced_ids(monkeypatch: pytest.MonkeyPatch):
    ids = ["anthropic/claude-sonnet-4", "openai/gpt-4o", "google/gemini-2.5-pro"]
    provider = _provider(monkeypatch, ids, OPENROUTER_BASE_URL)
    assert [m["id"] for m in provider.list_models()] == sorted(ids)


def test_openai_still_narrows_to_chat_families(monkeypatch: pytest.MonkeyPatch):
    ids = ["gpt-4o", "o3-mini", "text-embedding-3-small", "dall-e-3"]
    provider = _provider(monkeypatch, ids, None)
    assert [m["id"] for m in provider.list_models()] == ["gpt-4o", "o3-mini"]


def test_openrouter_default_model_is_namespaced():
    """A route with no model chosen must not fall back to a bare 'gpt-4o',
    which OpenRouter rejects — it wants the vendor/model form."""
    assert OpenAIProvider(api_key="k", base_url=OPENROUTER_BASE_URL)._model == "openai/gpt-4o"


def test_openai_default_model_unchanged():
    assert OpenAIProvider(api_key="k")._model == "gpt-4o"


def test_explicit_model_still_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    provider = OpenAIProvider(api_key="k", model="anthropic/claude-sonnet-4",
                              base_url=OPENROUTER_BASE_URL)
    assert provider._model == "anthropic/claude-sonnet-4"
