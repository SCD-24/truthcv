import time

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import modelrouting
import secretstore
from api.main import app
from modelrouting import Route, Routing


@pytest.fixture()
def client(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("AGENT_API_TOKEN", "shared-secret")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return TestClient(app)


def _hdr(v="shared-secret"):
    return {"X-Agent-Token": v}


def test_no_env_secret_404(client, monkeypatch):
    monkeypatch.delenv("AGENT_API_TOKEN")
    assert client.get("/api/agent/llm-credentials", headers=_hdr()).status_code == 404


def test_wrong_or_missing_header_404(client):
    assert client.get("/api/agent/llm-credentials").status_code == 404
    assert client.get("/api/agent/llm-credentials", headers=_hdr("nope")).status_code == 404


def test_api_key_path(client):
    secretstore.set_connection("claude", {"apiKey": "sk-ant-agent", "authMode": "apikey"})
    modelrouting.save(Routing(agent=Route("claude", "claude-opus-4-8")))
    body = client.get("/api/agent/llm-credentials", headers=_hdr()).json()
    assert body == {"authType": "api_key", "token": "sk-ant-agent", "model": "claude-opus-4-8"}


def test_oauth_path_uses_fresh_token(client, monkeypatch):
    secretstore.set_connection("claude", {
        "oauth": {"accessToken": "at", "refreshToken": "rt", "expiresAt": time.time() + 3600},
        "authMode": "subscription",
    })
    monkeypatch.setattr("api.routes.get_valid_access_token", lambda: "fresh-tok")
    body = client.get("/api/agent/llm-credentials", headers=_hdr()).json()
    assert body["authType"] == "oauth" and body["token"] == "fresh-tok"


def test_oauth_refresh_fails_503(client, monkeypatch):
    secretstore.set_connection("claude", {
        "oauth": {"accessToken": "at", "refreshToken": "rt", "expiresAt": time.time() + 3600},
        "authMode": "subscription",
    })

    def _raise():
        from connections.auth.claude import AuthError

        raise AuthError("boom")

    monkeypatch.setattr("api.routes.get_valid_access_token", _raise)
    resp = client.get("/api/agent/llm-credentials", headers=_hdr())
    assert resp.status_code == 503
    assert "boom" not in resp.text


def test_non_claude_agent_route_409(client):
    secretstore.set_connection("ollama", {"baseUrl": "http://x:11434"})
    modelrouting.save(Routing(agent=Route("ollama", "llama3.1")))
    assert client.get("/api/agent/llm-credentials", headers=_hdr()).status_code == 409


def test_nothing_configured_404(client):
    assert client.get("/api/agent/llm-credentials", headers=_hdr()).status_code == 404
