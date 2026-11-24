"""Provider factory: routing-aware resolution, per-connection cache, OpenRouter."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

import truthcv.integrations.modelrouting as modelrouting
import truthcv.infra.secretstore as secretstore
from truthcv.integrations.modelrouting import Route, Routing
from truthcv.integrations.providers import ProviderError, build_connection_provider, get_provider, reset_provider


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
    from truthcv.integrations.providers.fake import FakeProvider
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


def _dead_claude(api_key: str | None = "sk-ant-fb") -> None:
    import time
    conn = {
        "oauth": {"accessToken": "t", "refreshToken": "r",
                  "expiresAt": time.time() + 3600, "reauthRequired": True},
        "authMode": "subscription",
    }
    if api_key:
        conn["apiKey"] = api_key
    secretstore.set_connection("claude", conn)


def test_dead_claude_subscription_builds_api_key_provider():
    _dead_claude()
    provider = build_connection_provider("claude", None)
    assert provider._oauth is False


def test_dead_claude_subscription_without_key_stays_oauth():
    _dead_claude(api_key=None)
    assert build_connection_provider("claude", None)._oauth is True


def test_dead_codex_subscription_builds_api_key_provider(monkeypatch):
    from truthcv.integrations.connections.auth import codex as codex_auth

    secretstore.set_connection("codex", {
        "oauth": {"accessToken": "t", "refreshToken": "r", "expiresAt": 0},
        "authMode": "subscription", "apiKey": "sk-codex-fb",
    })

    def _dead(**_kw):
        raise codex_auth.AuthError("dead", reconnect_required=True)

    monkeypatch.setattr(codex_auth, "get_valid_access_token", _dead)
    provider = build_connection_provider("codex", None)
    assert provider._oauth_token is None


def test_cache_does_not_serve_oauth_provider_once_subscription_dies():
    import time
    secretstore.set_connection("claude", {
        "oauth": {"accessToken": "t", "refreshToken": "r", "expiresAt": time.time() + 3600},
        "authMode": "subscription", "apiKey": "sk-ant-fb",
    })
    modelrouting.save(Routing(default=Route("claude", "m")))
    assert get_provider()._oauth is True
    _dead_claude()  # the refresh path marks the record; nothing resets the cache
    assert get_provider()._oauth is False


def test_openrouter_uses_base_url():
    secretstore.set_connection("openrouter", {"apiKey": "sk-or-1"})
    provider = build_connection_provider("openrouter", "openrouter/auto")
    assert type(provider).__name__ == "OpenAIProvider"


def test_unknown_card_raises():
    with pytest.raises(ProviderError):
        build_connection_provider("copilot", None)
