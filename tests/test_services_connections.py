"""Unit tests for services.connections (error text and key-save policy)."""

from __future__ import annotations

import pytest

from providers import ProviderError
from services import connections as svc
from services.errors import BadRequest, NotFound


@pytest.fixture
def store(monkeypatch):
    calls = {"set": [], "clear": [], "reset": 0}
    monkeypatch.setattr(svc.secretstore, "encryption_available", lambda: True)
    monkeypatch.setattr(svc.secretstore, "get_connection", lambda p: {})
    monkeypatch.setattr(svc.secretstore, "set_connection", lambda p, u: calls["set"].append((p, u)))
    monkeypatch.setattr(svc.secretstore, "clear_mode", lambda p, m: calls["clear"].append((p, m)))
    monkeypatch.setattr(svc._providers, "reset_provider", lambda: calls.__setitem__("reset", calls["reset"] + 1))
    return calls


def test_require_card_unknown():
    with pytest.raises(NotFound, match=r"^Unknown connection 'nope'\.$"):
        svc.require_card("nope")


def test_start_login_gates():
    with pytest.raises(NotFound):
        svc.start_login("nope")
    with pytest.raises(BadRequest, match=r"^Subscription sign-in is not available for 'ollama'\.$"):
        svc.start_login("ollama")


def test_complete_login_unknown_and_auth_error(monkeypatch, store):
    with pytest.raises(NotFound, match=r"^Unknown connection 'ollama'\.$"):
        svc.complete_login("ollama", "c")

    def boom(code):
        raise svc.claude_auth.AuthError("bad code")

    monkeypatch.setattr(svc.claude_auth, "complete_login", boom)
    with pytest.raises(BadRequest, match="^bad code$"):
        svc.complete_login("claude", "c")
    assert store["reset"] == 0


def test_complete_login_resets_provider(monkeypatch, store):
    monkeypatch.setattr(svc.claude_auth, "complete_login", lambda code: None)
    svc.complete_login("claude", "c")
    assert store["reset"] == 1


def test_poll_login_unknown_and_unsupported(monkeypatch):
    with pytest.raises(NotFound):
        svc.poll_login("ollama")
    monkeypatch.delattr(svc.claude_auth, "poll_login", raising=False)
    with pytest.raises(BadRequest, match=r"^Provider 'claude' does not support polling\.$"):
        svc.poll_login("claude")


def test_save_key_requires_encryption(monkeypatch, store):
    monkeypatch.setattr(svc.secretstore, "encryption_available", lambda: False)
    with pytest.raises(BadRequest, match=r"^Set ENCRYPTION_KEY in \.env first\.$"):
        svc.save_key("codex", "sk", None, None)


def test_save_key_probe_errors_store_nothing(monkeypatch, store):
    def provider_err(card, body):
        raise ProviderError("bad key")

    monkeypatch.setattr(svc, "probe_key", provider_err)
    with pytest.raises(BadRequest, match="^bad key$"):
        svc.save_key("codex", "sk", None, None)

    def raw_err(card, body):
        raise RuntimeError("invalid x-api-key")

    monkeypatch.setattr(svc, "probe_key", raw_err)
    with pytest.raises(BadRequest, match="^RuntimeError: invalid x-api-key$"):
        svc.save_key("codex", "sk", None, None)
    assert store["set"] == [] and store["reset"] == 0


def test_save_key_flips_auth_mode_only_when_key_submitted(monkeypatch, store):
    monkeypatch.setattr(svc, "probe_key", lambda card, body: [{"id": "m"}])
    assert svc.save_key("claude", None, None, None) == [{"id": "m"}]
    assert store["set"] == [] and store["reset"] == 1
    svc.save_key("claude", "sk", None, None)
    assert store["set"] == [("claude", {"apiKey": "sk", "authMode": "apikey"})]


def test_logout_modes(monkeypatch, store):
    svc.logout("claude", "subscription")
    assert store["clear"] == [("claude", "subscription")]
    monkeypatch.setattr(svc.secretstore, "get_connection", lambda p: {"oauth": {"accessToken": "t"}})
    svc.logout("claude")
    assert store["clear"][-1] == ("claude", "subscription")
    monkeypatch.setattr(svc.secretstore, "get_connection", lambda p: {})
    svc.logout("claude")
    assert store["clear"][-1] == ("claude", "apikey")
    assert store["reset"] == 3
