"""/api/agent/run and /api/agent/status: passthrough, 503 on agent down, token forwarding."""

from __future__ import annotations

import json
import os
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_urlopen_response(payload: dict):
    """Return a mock context-manager that urllib.request.urlopen yields."""
    body = json.dumps(payload).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _make_url_error():
    """Return a URLError as raised when the agent is unreachable."""
    return urllib.error.URLError("Connection refused")


# ---------------------------------------------------------------------------
# GET /api/agent/status
# ---------------------------------------------------------------------------

class TestGetAgentStatus:
    def test_happy_path_returns_status(self, client, data_dir, monkeypatch):
        """Upstream JSON is forwarded verbatim."""
        upstream = {
            "running": False,
            "lastStartedAt": "2024-01-15T09:00:00.000Z",
            "lastFinishedAt": "2024-01-15T09:05:00.000Z",
            "lastExitCode": 0,
        }
        monkeypatch.setenv("AGENT_API_TOKEN", "test-token-abc")
        with patch("urllib.request.urlopen", return_value=_make_urlopen_response(upstream)):
            r = client.get("/api/agent/status")
        assert r.status_code == 200
        body = r.json()
        assert body["running"] is False
        assert body["lastStartedAt"] == upstream["lastStartedAt"]
        assert body["lastFinishedAt"] == upstream["lastFinishedAt"]
        assert body["lastExitCode"] == 0

    def test_running_true_forwarded(self, client, data_dir, monkeypatch):
        """running:true is preserved."""
        upstream = {
            "running": True,
            "lastStartedAt": "2024-01-15T10:00:00.000Z",
            "lastFinishedAt": None,
            "lastExitCode": None,
        }
        monkeypatch.setenv("AGENT_API_TOKEN", "test-token-abc")
        with patch("urllib.request.urlopen", return_value=_make_urlopen_response(upstream)):
            r = client.get("/api/agent/status")
        assert r.status_code == 200
        assert r.json()["running"] is True

    def test_upstream_down_returns_503(self, client, data_dir, monkeypatch):
        """Connection refused -> 503 with friendly detail."""
        monkeypatch.setenv("AGENT_API_TOKEN", "test-token-abc")
        with patch("urllib.request.urlopen", side_effect=_make_url_error()):
            r = client.get("/api/agent/status")
        assert r.status_code == 503
        assert r.json()["detail"] == "Agent service unreachable"

    def test_x_agent_token_forwarded(self, client, data_dir, monkeypatch):
        """X-Agent-Token header carries AGENT_API_TOKEN to the supervisor."""
        monkeypatch.setenv("AGENT_API_TOKEN", "secret-forwarded-token")
        upstream = {"running": False, "lastStartedAt": None, "lastFinishedAt": None, "lastExitCode": None}

        captured_headers = {}

        def fake_urlopen(req, timeout=None):
            captured_headers.update(dict(req.headers))
            return _make_urlopen_response(upstream)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            r = client.get("/api/agent/status")

        assert r.status_code == 200
        # urllib capitalises the first letter of each header word
        assert captured_headers.get("X-agent-token") == "secret-forwarded-token"


# ---------------------------------------------------------------------------
# POST /api/agent/run
# ---------------------------------------------------------------------------

class TestPostAgentRun:
    def test_happy_path_started_true(self, client, data_dir, monkeypatch):
        """Fire-and-forget trigger returns {started:true, running:true}."""
        upstream = {"started": True, "running": True}
        monkeypatch.setenv("AGENT_API_TOKEN", "test-token-abc")
        with patch("urllib.request.urlopen", return_value=_make_urlopen_response(upstream)):
            r = client.post("/api/agent/run")
        assert r.status_code == 200
        body = r.json()
        assert body["started"] is True
        assert body["running"] is True

    def test_already_running_returns_started_false(self, client, data_dir, monkeypatch):
        """When a run is active upstream returns {started:false, running:true}."""
        upstream = {"started": False, "running": True}
        monkeypatch.setenv("AGENT_API_TOKEN", "test-token-abc")
        with patch("urllib.request.urlopen", return_value=_make_urlopen_response(upstream)):
            r = client.post("/api/agent/run")
        assert r.status_code == 200
        body = r.json()
        assert body["started"] is False
        assert body["running"] is True

    def test_upstream_down_returns_503(self, client, data_dir, monkeypatch):
        """Connection refused -> 503 with friendly detail."""
        monkeypatch.setenv("AGENT_API_TOKEN", "test-token-abc")
        with patch("urllib.request.urlopen", side_effect=_make_url_error()):
            r = client.post("/api/agent/run")
        assert r.status_code == 503
        assert r.json()["detail"] == "Agent service unreachable"

    def test_x_agent_token_forwarded_on_run(self, client, data_dir, monkeypatch):
        """X-Agent-Token header carries AGENT_API_TOKEN when triggering a run."""
        monkeypatch.setenv("AGENT_API_TOKEN", "run-token-xyz")
        upstream = {"started": True, "running": True}

        captured_headers = {}

        def fake_urlopen(req, timeout=None):
            captured_headers.update(dict(req.headers))
            return _make_urlopen_response(upstream)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            r = client.post("/api/agent/run")

        assert r.status_code == 200
        assert captured_headers.get("X-agent-token") == "run-token-xyz"
