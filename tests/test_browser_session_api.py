"""/api/browser/session: forwarding, refusal passthrough, 503 when the browser is down."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def _response(payload: dict):
    body = json.dumps(payload).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _http_error(status: int, payload: dict):
    return urllib.error.HTTPError(
        url="http://browser:8932/session",
        code=status,
        msg="refused",
        hdrs=None,
        fp=None,
    )


def _http_error_with_body(status: int, payload: dict):
    body = io.BytesIO(json.dumps(payload).encode())
    return urllib.error.HTTPError(
        url="http://browser:8932/session",
        code=status,
        msg="refused",
        hdrs=None,
        fp=body,
    )


class TestGetSession:
    def test_reports_no_session(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        upstream = {"open": False, "url": None, "startedAt": None, "evictDeadline": None}
        with patch("urllib.request.urlopen", return_value=_response(upstream)):
            r = client.get("/api/browser/session")
        assert r.status_code == 200
        assert r.json()["open"] is False

    def test_reports_an_open_session(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        upstream = {
            "open": True,
            "url": "https://example.com/login",
            "startedAt": "2026-08-25T12:00:00.000Z",
            "evictDeadline": None,
        }
        with patch("urllib.request.urlopen", return_value=_response(upstream)):
            r = client.get("/api/browser/session")
        body = r.json()
        assert body["open"] is True
        assert body["url"] == "https://example.com/login"

    def test_browser_down_is_503(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            r = client.get("/api/browser/session")
        assert r.status_code == 503


class TestPostSession:
    def test_opens_a_session(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        upstream = {
            "open": True,
            "url": "https://example.com/login",
            "startedAt": "2026-08-25T12:00:00.000Z",
            "evictDeadline": None,
        }
        with patch("urllib.request.urlopen", return_value=_response(upstream)):
            r = client.post("/api/browser/session", json={"url": "https://example.com/login"})
        assert r.status_code == 200
        assert r.json()["open"] is True

    def test_agent_running_is_forwarded_as_409(self, client, monkeypatch):
        """The UI needs to distinguish 'busy' from 'broken' — a 409 must not become a 503."""
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        with patch("urllib.request.urlopen", side_effect=_http_error(409, {"reason": "agent_running"})):
            r = client.post("/api/browser/session", json={"url": "https://example.com/login"})
        assert r.status_code == 409

    def test_a_non_http_url_is_rejected_before_forwarding(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        with patch("urllib.request.urlopen") as urlopen:
            r = client.post("/api/browser/session", json={"url": "file:///etc/passwd"})
        assert r.status_code == 422
        assert urlopen.call_count == 0

    def test_session_open_refusal_carries_the_open_url(self, client, monkeypatch):
        """So the UI can offer 'go back to your session at <url>' instead of a bare refusal."""
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        error = _http_error_with_body(409, {"reason": "session_open", "url": "https://example.com/login"})
        with patch("urllib.request.urlopen", side_effect=error):
            r = client.post("/api/browser/session", json={"url": "https://other.example.com"})
        assert r.status_code == 409
        assert r.json()["detail"] == {"reason": "session_open", "url": "https://example.com/login"}

    def test_agent_running_refusal_carries_its_reason(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        error = _http_error_with_body(409, {"reason": "agent_running"})
        with patch("urllib.request.urlopen", side_effect=error):
            r = client.post("/api/browser/session", json={"url": "https://example.com/login"})
        assert r.status_code == 409
        assert r.json()["detail"] == {"reason": "agent_running"}

    def test_a_refusal_with_no_body_still_forwards_the_status(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        with patch("urllib.request.urlopen", side_effect=_http_error(409, {"reason": "agent_running"})):
            r = client.post("/api/browser/session", json={"url": "https://example.com/login"})
        assert r.status_code == 409
        assert r.json()["detail"] == {"reason": "refused"}


class TestDeleteSession:
    def test_closes_the_session(self, client, monkeypatch):
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        with patch("urllib.request.urlopen", return_value=_response({"closed": True})):
            r = client.delete("/api/browser/session")
        assert r.status_code == 200
        assert r.json()["closed"] is True
