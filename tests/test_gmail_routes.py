"""Gmail routes: OAuth start/callback and the response-tracking sync trigger.

Patterned on tests/test_auth_api.py and tests/test_jev_settings_api.py. The
gate (require_gmail_tracking_enabled) requires a saved Jev API key AND
useForEmailTracking enabled on the secretstore "jev" connection; every route
here is gated on it except GET /api/gmail/status. The OAuth exchange and the
gmailsync sync itself are always mocked — no live network call is made.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import secretstore
from api.main import app
from connections.auth import gmail as gmail_auth

FERNET_KEY = "h2oN5GQVeWVhciVjWNImtAmWFyPGlrWvDCq8vXuqfmo="


@pytest.fixture()
def client(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    # An exported JEV_API_KEY would otherwise fill secretstore.get_connection's
    # apiKey from the environment, opening the gate even for the gate-closed
    # tests below and letting them hit the real network.
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    return TestClient(app)


def _open_gate() -> None:
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForEmailTracking": True})


def test_gate_closed_start_is_403(client):
    resp = client.post("/api/auth/gmail/start")
    assert resp.status_code == 403


def test_gate_closed_callback_redirects_with_error(client):
    """The callback is a browser redirect target, so a closed gate redirects
    with gmailError=not_enabled instead of rendering a 403 JSON body."""
    resp = client.get(
        "/api/auth/gmail/callback",
        params={"code": "c", "state": "s"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 307)
    assert "gmailError=not_enabled" in resp.headers["location"]


def test_gate_closed_sync_is_403(client):
    resp = client.post("/api/gmail/responses/sync", json={})
    assert resp.status_code == 403


def test_gate_closed_when_key_set_but_toggle_off(client):
    """A saved key alone, without the explicit useForEmailTracking opt-in, must
    still 403 — the same rule the underlying Jev cross-check gate follows."""
    secretstore.set_connection("jev", {"apiKey": "jev_secret"})
    resp = client.post("/api/auth/gmail/start")
    assert resp.status_code == 403


def test_gate_open_start_returns_auth_url(client, monkeypatch):
    _open_gate()
    monkeypatch.setattr(
        "connections.auth.gmail.start_login",
        lambda redirect_uri: {"flow": "browser", "authUrl": "https://accounts.google.com/o/oauth2/v2/auth?state=s1"},
    )
    resp = client.post("/api/auth/gmail/start")
    assert resp.status_code == 200
    body = resp.json()
    assert body["flow"] == "browser"
    assert "authUrl" in body and body["authUrl"]


def test_gate_open_callback_completes_login(client, monkeypatch):
    _open_gate()
    calls = []

    def fake_complete(code, state):
        calls.append((code, state))
        return {"email": "operator@example.com"}

    monkeypatch.setattr("connections.auth.gmail.complete_login", fake_complete)
    resp = client.get(
        "/api/auth/gmail/callback",
        params={"code": "authcode", "state": "state1"},
        follow_redirects=False,
    )
    assert resp.status_code in (307, 308)
    assert resp.headers["location"] == "/"
    assert calls == [("authcode", "state1")]


def test_gate_open_callback_denied_consent_redirects_with_error(client):
    """Google's own denied-consent redirect (?error=access_denied, no code/state)
    must redirect back to the app root with a gmailError param, not 422."""
    _open_gate()
    resp = client.get(
        "/api/auth/gmail/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )
    assert resp.status_code in (307, 308)
    assert resp.headers["location"] == "/?gmailError=access_denied"


def test_gate_open_callback_missing_code_redirects_with_error(client):
    """A callback hit with no code/state/error at all must still redirect, not 422."""
    _open_gate()
    resp = client.get("/api/auth/gmail/callback", follow_redirects=False)
    assert resp.status_code in (307, 308)
    assert resp.headers["location"] == "/?gmailError=missing_code"


def test_gate_open_callback_auth_error_redirects_with_error(client, monkeypatch):
    """A failed token exchange (AuthError) must redirect, not surface a JSON 400."""
    _open_gate()

    def fake_complete(code, state):
        raise gmail_auth.AuthError("exchange failed")

    monkeypatch.setattr("connections.auth.gmail.complete_login", fake_complete)
    resp = client.get(
        "/api/auth/gmail/callback",
        params={"code": "authcode", "state": "state1"},
        follow_redirects=False,
    )
    assert resp.status_code in (307, 308)
    assert resp.headers["location"] == "/?gmailError=auth_failed"


def test_gate_open_sync_returns_run_sync_summary(client, monkeypatch):
    _open_gate()
    summary = {"skipped": False, "last_synced_at": 123.0, "processed": 2, "suggestions": 1}
    calls = []

    def fake_run_sync(*, force=False):
        calls.append(force)
        return summary

    monkeypatch.setattr("gmailsync.service.run_sync", fake_run_sync)
    resp = client.post("/api/gmail/responses/sync", json={})
    assert resp.status_code == 200
    assert resp.json() == summary
    assert calls == [False]


def test_gate_open_sync_passes_force_flag(client, monkeypatch):
    _open_gate()
    calls = []
    monkeypatch.setattr(
        "gmailsync.service.run_sync",
        lambda *, force=False: calls.append(force) or {"skipped": False, "last_synced_at": 1.0, "processed": 0, "suggestions": 0},
    )
    resp = client.post("/api/gmail/responses/sync", json={"force": True})
    assert resp.status_code == 200
    assert calls == [True]
