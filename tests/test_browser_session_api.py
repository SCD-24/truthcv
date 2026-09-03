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

    def test_a_close_still_waiting_for_the_browser_to_exit_is_not_reported_as_closed(
        self, client, monkeypatch
    ):
        """The session server confirms death before reporting closed=true (see
        browser/session-server.js close()); the ordinary response while it
        waits is closed=false, closing=true, and that distinction must survive
        the API layer rather than collapsing to a bare closed=false."""
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        with patch(
            "urllib.request.urlopen",
            return_value=_response({"closed": False, "closing": True}),
        ):
            r = client.delete("/api/browser/session")
        assert r.status_code == 200
        body = r.json()
        assert body["closed"] is False
        assert body["closing"] is True

    def test_a_close_refused_during_the_reservation_window_is_distinguished_from_no_session(
        self, client, monkeypatch
    ):
        """A close arriving while open() has only a reservation (no browser
        launched yet) is refused as closed=false, reserving=true — distinct
        from closed=false, closing=false, which means no session existed at
        all. See browser/session-server.js close()."""
        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        with patch(
            "urllib.request.urlopen",
            return_value=_response({"closed": False, "reserving": True}),
        ):
            r = client.delete("/api/browser/session")
        assert r.status_code == 200
        body = r.json()
        assert body["closed"] is False
        assert body["closing"] is False
        assert body["reserving"] is True

    def test_accepted_close_with_closing_true_clears_matching_host_blockers(self, client, monkeypatch, data_dir):
        """When a session closes successfully, login blockers for matching hosts are cleared."""
        import screening.store as store

        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        
        # Create a login-blocked approved screening
        s = store.create({
            "company": "Acme",
            "role": "Dev",
            "verdict": "passed",
            "url": "https://acme.wd3.myworkdayjobs.com/careers/job/1"
        })
        store.set_approval(s.id, "approved")
        store.record_apply_failure(
            s.id,
            "sign-in required",
            blocker="login_required",
            signin_url="https://acme.wd3.myworkdayjobs.com/login"
        )
        
        # Mock the session server responses: GET /session returns the session, 
        # POST /session/close returns closing=true
        with patch("urllib.request.urlopen") as urlopen_mock:
            # side_effect list for sequential calls
            urlopen_mock.side_effect = [
                _response({"url": "https://acme.wd3.myworkdayjobs.com/login"}),  # GET /session
                _response({"closed": False, "closing": True})  # POST /session/close
            ]
            r = client.delete("/api/browser/session")
        
        assert r.status_code == 200
        body = r.json()
        assert body["closing"] is True
        assert body["signinsCleared"] == 1
        
        # Verify the blocker was actually cleared
        s_after = store.get(s.id)
        assert s_after.apply_blocker == ""
        assert s_after.signin_url == ""

    def test_accepted_close_with_closed_true_clears_matching_host_blockers(self, client, monkeypatch, data_dir):
        """When closed=true, blockers are also cleared."""
        import screening.store as store

        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        
        s = store.create({
            "company": "Acme",
            "role": "Dev",
            "verdict": "passed",
            "url": "https://acme.wd3.myworkdayjobs.com/careers/job/1"
        })
        store.set_approval(s.id, "approved")
        store.record_apply_failure(
            s.id,
            "sign-in required",
            blocker="login_required",
            signin_url="https://acme.wd3.myworkdayjobs.com/login"
        )
        
        with patch("urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.side_effect = [
                _response({"url": "https://acme.wd3.myworkdayjobs.com/login"}),
                _response({"closed": True, "closing": False})
            ]
            r = client.delete("/api/browser/session")
        
        assert r.status_code == 200
        body = r.json()
        assert body["closed"] is True
        assert body["signinsCleared"] == 1

    def test_no_session_does_not_clear_blockers(self, client, monkeypatch, data_dir):
        """When no session exists (reserving=true), no blockers are cleared."""
        import screening.store as store

        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        
        s = store.create({
            "company": "Acme",
            "role": "Dev",
            "verdict": "passed",
            "url": "https://acme.wd3.myworkdayjobs.com/careers/job/1"
        })
        store.set_approval(s.id, "approved")
        store.record_apply_failure(
            s.id,
            "sign-in required",
            blocker="login_required",
            signin_url="https://acme.wd3.myworkdayjobs.com/login"
        )
        
        with patch("urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.side_effect = [
                _response({"url": None}),  # No session
                _response({"closed": False, "reserving": True})
            ]
            r = client.delete("/api/browser/session")
        
        assert r.status_code == 200
        assert r.json()["signinsCleared"] == 0
        
        # Blocker should still be there
        assert store.get(s.id).apply_blocker == "login_required"

    def test_different_host_blockers_are_not_cleared(self, client, monkeypatch, data_dir):
        """Blockers for a different host are left untouched."""
        import screening.store as store

        monkeypatch.setenv("AGENT_API_TOKEN", "t")
        
        s = store.create({
            "company": "Globex",
            "role": "Dev",
            "verdict": "passed",
            "url": "https://globex.example.com/jobs/1"
        })
        store.set_approval(s.id, "approved")
        store.record_apply_failure(
            s.id,
            "sign-in required",
            blocker="login_required",
            signin_url="https://globex.example.com/login"
        )
        
        with patch("urllib.request.urlopen") as urlopen_mock:
            urlopen_mock.side_effect = [
                _response({"url": "https://acme.wd3.myworkdayjobs.com/login"}),  # Different host
                _response({"closed": False, "closing": True})
            ]
            r = client.delete("/api/browser/session")
        
        assert r.status_code == 200
        assert r.json()["signinsCleared"] == 0
        
        # Blocker should still be there
        assert store.get(s.id).apply_blocker == "login_required"
