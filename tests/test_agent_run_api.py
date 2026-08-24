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


# ---------------------------------------------------------------------------
# POST /api/agent/cancel
# ---------------------------------------------------------------------------

class TestPostAgentCancel:
    def test_happy_path_cancelled_true(self, client, data_dir, monkeypatch):
        """A run in progress is signalled: {cancelled:true, running:true}.

        `running` stays true because the cancel is fire-and-forget — the run is
        signalled, not yet reaped.
        """
        upstream = {"cancelled": True, "running": True}
        monkeypatch.setenv("AGENT_API_TOKEN", "test-token-abc")
        with patch("urllib.request.urlopen", return_value=_make_urlopen_response(upstream)):
            r = client.post("/api/agent/cancel")
        assert r.status_code == 200
        body = r.json()
        assert body["cancelled"] is True
        assert body["running"] is True

    def test_nothing_running_returns_cancelled_false(self, client, data_dir, monkeypatch):
        """Cancelling when idle is a no-op, not an error."""
        upstream = {"cancelled": False, "running": False}
        monkeypatch.setenv("AGENT_API_TOKEN", "test-token-abc")
        with patch("urllib.request.urlopen", return_value=_make_urlopen_response(upstream)):
            r = client.post("/api/agent/cancel")
        assert r.status_code == 200
        body = r.json()
        assert body["cancelled"] is False
        assert body["running"] is False

    def test_upstream_down_returns_503(self, client, data_dir, monkeypatch):
        """Connection refused -> 503 with friendly detail."""
        monkeypatch.setenv("AGENT_API_TOKEN", "test-token-abc")
        with patch("urllib.request.urlopen", side_effect=_make_url_error()):
            r = client.post("/api/agent/cancel")
        assert r.status_code == 503
        assert r.json()["detail"] == "Agent service unreachable"

    def test_x_agent_token_forwarded_on_cancel(self, client, data_dir, monkeypatch):
        """X-Agent-Token header carries AGENT_API_TOKEN when cancelling."""
        monkeypatch.setenv("AGENT_API_TOKEN", "cancel-token-xyz")
        upstream = {"cancelled": True, "running": True}

        captured_headers = {}

        def fake_urlopen(req, timeout=None):
            captured_headers.update(dict(req.headers))
            return _make_urlopen_response(upstream)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            r = client.post("/api/agent/cancel")

        assert r.status_code == 200
        assert captured_headers.get("X-agent-token") == "cancel-token-xyz"

    def test_supervisor_path_is_cancel(self, client, data_dir, monkeypatch):
        """The route forwards to the supervisor's /cancel, not /run."""
        monkeypatch.setenv("AGENT_API_TOKEN", "test-token-abc")
        upstream = {"cancelled": True, "running": True}
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            return _make_urlopen_response(upstream)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.post("/api/agent/cancel")

        assert captured["url"].endswith("/cancel")
        assert captured["method"] == "POST"


class TestAgentStatusCancelFields:
    def test_cancelling_and_last_cancelled_forwarded(self, client, data_dir, monkeypatch):
        """A stopping run reports cancelling; a cancelled one reports lastCancelled."""
        upstream = {
            "running": True,
            "cancelling": True,
            "lastStartedAt": "2024-01-15T10:00:00.000Z",
            "lastFinishedAt": None,
            "lastExitCode": None,
            "lastCancelled": False,
        }
        monkeypatch.setenv("AGENT_API_TOKEN", "test-token-abc")
        with patch("urllib.request.urlopen", return_value=_make_urlopen_response(upstream)):
            r = client.get("/api/agent/status")
        assert r.json()["cancelling"] is True

        upstream = {
            "running": False,
            "cancelling": False,
            "lastStartedAt": "2024-01-15T10:00:00.000Z",
            "lastFinishedAt": "2024-01-15T10:04:00.000Z",
            "lastExitCode": 143,
            "lastCancelled": True,
        }
        with patch("urllib.request.urlopen", return_value=_make_urlopen_response(upstream)):
            r = client.get("/api/agent/status")
        body = r.json()
        assert body["lastCancelled"] is True
        assert body["lastExitCode"] == 143

    def test_missing_cancel_fields_default_false(self, client, data_dir, monkeypatch):
        """An older supervisor that sends neither field must not break status."""
        upstream = {
            "running": False,
            "lastStartedAt": None,
            "lastFinishedAt": None,
            "lastExitCode": None,
        }
        monkeypatch.setenv("AGENT_API_TOKEN", "test-token-abc")
        with patch("urllib.request.urlopen", return_value=_make_urlopen_response(upstream)):
            r = client.get("/api/agent/status")
        body = r.json()
        assert body["cancelling"] is False
        assert body["lastCancelled"] is False
