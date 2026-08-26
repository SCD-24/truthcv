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
    assert body == {
        "authType": "api_key",
        "token": "sk-ant-agent",
        "model": "claude-opus-4-8",
        # Empty for Anthropic itself: the CLI keeps its built-in endpoint.
        "baseUrl": "",
        "provider": "claude",
        "wire": "anthropic-messages",
    }


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


def test_non_ascii_header_404(client):
    # Raw non-ASCII bytes on the wire (as an ISO-8859-1/UTF-8 client might send)
    # must not crash hmac.compare_digest into a distinguishable 500 — every
    # mismatch, ASCII or not, is a plain 404.
    resp = client.get(
        "/api/agent/llm-credentials", headers=[(b"X-Agent-Token", b"n\xc3\xb6pe")]
    )
    assert resp.status_code == 404


def test_codex_route_returns_openai_wire(client):
    secretstore.set_connection("codex", {"apiKey": "sk-codex-1"})
    modelrouting.save(Routing(agent=Route("codex", "gpt-5")))
    body = client.get("/api/agent/llm-credentials", headers=_hdr()).json()
    assert body == {
        "authType": "api_key",
        "token": "sk-codex-1",
        "model": "gpt-5",
        "baseUrl": "",
        "provider": "codex",
        "wire": "openai-chat-completions",
    }


def test_codex_route_without_key_404(client):
    modelrouting.save(Routing(agent=Route("codex", "gpt-5")))
    assert client.get("/api/agent/llm-credentials", headers=_hdr()).status_code == 404


def test_openrouter_route_returns_openai_wire(client):
    secretstore.set_connection("openrouter", {"apiKey": "sk-or-1"})
    modelrouting.save(Routing(agent=Route("openrouter", "stealth/ox-alpha")))
    body = client.get("/api/agent/llm-credentials", headers=_hdr()).json()
    assert body == {
        "authType": "api_key",
        "token": "sk-or-1",
        "model": "stealth/ox-alpha",
        "baseUrl": "https://openrouter.ai/api/v1",
        "provider": "openrouter",
        "wire": "openai-chat-completions",
    }


def test_ollama_route_returns_tokenless_credentials(client):
    secretstore.set_connection("ollama", {"baseUrl": "http://x:11434"})
    modelrouting.save(Routing(agent=Route("ollama", "llama3.1")))
    body = client.get("/api/agent/llm-credentials", headers=_hdr()).json()
    assert body == {
        "authType": "url",
        "token": "",
        "model": "llama3.1",
        "baseUrl": "http://x:11434",
        "provider": "ollama",
        "wire": "openai-chat-completions",
    }


def test_ollama_route_without_stored_base_url_falls_back_to_env_default(client, monkeypatch):
    # Unlike the keyed cards, ollama has no unconfigured state to 404 on:
    # secretstore.get_connection("ollama") fills an absent baseUrl from
    # OLLAMA_HOST and, failing that, from the documented localhost default
    # (compose sets OLLAMA_HOST=http://ollama:11434). The route therefore
    # serves that fallback rather than refusing.
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama:11434")
    modelrouting.save(Routing(agent=Route("ollama", "llama3.1")))
    body = client.get("/api/agent/llm-credentials", headers=_hdr()).json()
    assert body == {
        "authType": "url",
        "token": "",
        "model": "llama3.1",
        "baseUrl": "http://ollama:11434",
        "provider": "ollama",
        "wire": "openai-chat-completions",
    }


def test_nothing_configured_404(client):
    assert client.get("/api/agent/llm-credentials", headers=_hdr()).status_code == 404


def test_response_shape_matches_agent_parser(client):
    # agent/agent-config.js's llm_credentials verb parses the 200 body by
    # reading exactly these keys, in this shape — a field renamed or dropped
    # here breaks the agent's parser silently. This test is the seam guard
    # between the two. The original four keys (authType, token, model,
    # baseUrl) still parse for the agent-side reader; provider and wire are
    # additive.
    secretstore.set_connection("claude", {"apiKey": "sk-ant-agent", "authMode": "apikey"})
    modelrouting.save(Routing(agent=Route("claude", "claude-opus-4-8")))
    body = client.get("/api/agent/llm-credentials", headers=_hdr()).json()
    assert set(body.keys()) == {"authType", "token", "model", "baseUrl", "provider", "wire"}
    assert {"authType", "token", "model", "baseUrl"} <= set(body.keys())


def test_openrouter_route_without_key_404(client):
    modelrouting.save(Routing(agent=Route("openrouter", "stealth/ox-alpha")))
    assert client.get("/api/agent/llm-credentials", headers=_hdr()).status_code == 404
