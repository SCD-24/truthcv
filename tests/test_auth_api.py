import time

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import secretstore
from api.main import app


@pytest.fixture()
def client(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    from providers import reset_provider
    reset_provider()
    return TestClient(app)


def test_status_lists_cards_without_secrets(client):
    secretstore.set_connection("claude", {"apiKey": "sk-ant-1", "authMode": "apikey"})
    body = client.get("/api/auth/status").json()
    cards = {c["provider"]: c for c in body["connections"]}
    assert set(cards) == {"claude", "codex", "openrouter", "ollama"}
    assert cards["claude"]["apiKeyConnected"] is True
    assert "sk-ant-1" not in str(body)


def test_start_claude_login(client):
    body = client.post("/api/auth/claude/start").json()
    assert body["flow"] == "paste-code" and "authUrl" in body


def test_start_unsupported_provider_400(client):
    assert client.post("/api/auth/openrouter/start").status_code == 400


def test_unknown_provider_404(client):
    assert client.get("/api/auth/copilot/models").status_code == 404


def test_key_validation_failure_stores_nothing(client, monkeypatch):
    from providers import ProviderError

    def boom(card, body):
        raise ProviderError("bad key")

    monkeypatch.setattr("api.routes._probe_key", boom)
    resp = client.post("/api/auth/codex/key", json={"apiKey": "sk-bad"})
    assert resp.status_code == 400
    assert "apiKey" not in secretstore.load_store().get("connections", {}).get("codex", {})


def test_logout_subscription_clears_oauth_only(client):
    secretstore.set_connection("claude", {
        "oauth": {"accessToken": "t", "expiresAt": time.time() + 100},
        "apiKey": "sk-keep",
    })
    body = client.post("/api/auth/claude/logout?mode=subscription").json()
    assert body["subscriptionConnected"] is False
    assert secretstore.get_connection("claude")["apiKey"] == "sk-keep"
