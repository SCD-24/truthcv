"""Provider factory: routing-aware resolution, per-connection cache, OpenRouter."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

import modelrouting
import secretstore
from modelrouting import Route, Routing
from providers import ProviderError, build_connection_provider, get_provider, reset_provider


@pytest.fixture(autouse=True)
def clean(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    for var in ("LLM_PROVIDER", "LLM_MODEL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    reset_provider()
    yield
    reset_provider()


def test_fake_env_short_circuit(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    from providers.fake import FakeProvider
    assert isinstance(get_provider(), FakeProvider)


def test_routing_default_selects_connection():
    secretstore.set_connection("claude", {"apiKey": "sk-ant-1", "authMode": "apikey"})
    modelrouting.save(Routing(default=Route("claude", "claude-opus-4-8")))
    provider = get_provider()
    assert type(provider).__name__ == "AnthropicProvider"
    assert provider._model == "claude-opus-4-8"


def test_task_route_beats_default():
    secretstore.set_connection("claude", {"apiKey": "sk-ant-1", "authMode": "apikey"})
    secretstore.set_connection("ollama", {"baseUrl": "http://box:11434"})
    modelrouting.save(Routing(
        tasks={"keywords": Route("ollama", "llama3.1")},
        default=Route("claude", ""),
    ))
    assert type(get_provider("keywords")).__name__ == "OllamaProvider"
    assert type(get_provider("tailor")).__name__ == "AnthropicProvider"


def test_legacy_env_fallback_without_routing(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai-1")
    assert type(get_provider()).__name__ == "OpenAIProvider"


def test_oauth_claude_when_record_present():
    import time
    secretstore.set_connection("claude", {
        "oauth": {"accessToken": "t", "refreshToken": "r", "expiresAt": time.time() + 3600},
        "authMode": "subscription",
    })
    provider = build_connection_provider("claude", None)
    assert provider._oauth is True


def test_openrouter_uses_base_url():
    secretstore.set_connection("openrouter", {"apiKey": "sk-or-1"})
    provider = build_connection_provider("openrouter", "openrouter/auto")
    assert type(provider).__name__ == "OpenAIProvider"


def test_unknown_card_raises():
    with pytest.raises(ProviderError):
        build_connection_provider("copilot", None)
