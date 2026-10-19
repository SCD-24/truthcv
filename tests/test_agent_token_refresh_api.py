import time

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import secretstore
from api.main import app
from connections.auth import codex as codex_auth
from connections.auth.claude import AuthError

URL = "/api/agent/llm-token/refresh"
SHA = "ab" * 32


@pytest.fixture()
def client(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("AGENT_API_TOKEN", "shared-secret")
    return TestClient(app)


def _hdr(v="shared-secret"):
    return {"X-Agent-Token": v}


def _body(provider="claude", sha=SHA):
    return {"provider": provider, "rejectedTokenSha256": sha}


def _oauth(provider, mode="subscription"):
    secretstore.set_connection(provider, {
        "oauth": {"accessToken": "at", "refreshToken": "rt", "expiresAt": time.time() + 3600},
        "authMode": mode,
    })


def test_missing_and_wrong_header_404(client):
    assert client.post(URL, json=_body()).status_code == 404
    assert client.post(URL, json=_body(), headers=_hdr("nope")).status_code == 404


def test_apikey_mode_404(client):
    _oauth("claude", mode="apikey")
    assert client.post(URL, json=_body(), headers=_hdr()).status_code == 404


def test_no_oauth_404(client):
    assert client.post(URL, json=_body("codex"), headers=_hdr()).status_code == 404


def test_bad_provider_422(client):
    assert client.post(URL, json=_body("openrouter"), headers=_hdr()).status_code == 422


@pytest.mark.parametrize("sha", ["abc", "g" * 64, "a" * 65, ""])
def test_bad_sha_422(client, sha):
    assert client.post(URL, json=_body(sha=sha), headers=_hdr()).status_code == 422


def test_claude_forwards_sha(client, monkeypatch):
    _oauth("claude")
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return "new-tok"

    monkeypatch.setattr("api.routes.get_valid_access_token", fake)
    resp = client.post(URL, json=_body(sha=SHA.upper()), headers=_hdr())
    assert resp.status_code == 200 and resp.json() == {"token": "new-tok"}
    assert seen == {"rejected_sha256": SHA}


def test_codex_forwards_sha(client, monkeypatch):
    _oauth("codex")
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return "codex-tok"

    monkeypatch.setattr(codex_auth, "get_valid_access_token", fake)
    resp = client.post(URL, json=_body("codex"), headers=_hdr())
    assert resp.status_code == 200 and resp.json() == {"token": "codex-tok"}
    assert seen == {"rejected_sha256": SHA}


def test_claude_auth_error_503(client, monkeypatch):
    _oauth("claude")

    def boom(**kw):
        raise AuthError("boom")

    monkeypatch.setattr("api.routes.get_valid_access_token", boom)
    resp = client.post(URL, json=_body(), headers=_hdr())
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Claude subscription needs reconnecting."


def test_codex_auth_error_503(client, monkeypatch):
    _oauth("codex")

    def boom(**kw):
        raise codex_auth.AuthError("boom")

    monkeypatch.setattr(codex_auth, "get_valid_access_token", boom)
    resp = client.post(URL, json=_body("codex"), headers=_hdr())
    assert resp.status_code == 503
    assert resp.json()["detail"] == "ChatGPT subscription needs reconnecting."
