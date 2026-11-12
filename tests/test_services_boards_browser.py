"""Unit tests for truthcv.services.gmail (tracking/login/status), truthcv.services.job_boards and truthcv.services.browser."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

import truthcv.infra.secretstore as secretstore
from truthcv.services import browser, gmail, job_boards
from truthcv.services.errors import BadRequest, NotFound, Unavailable, UpstreamRefused

FERNET_KEY = "h2oN5GQVeWVhciVjWNImtAmWFyPGlrWvDCq8vXuqfmo="


@pytest.fixture(autouse=True)
def encryption(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_API_TOKEN", "t")


def _open_gate():
    secretstore.set_connection("jev", {"apiKey": "k", "useForEmailTracking": True})


# --- gmail -----------------------------------------------------------------

def test_tracking_enabled_needs_key_and_toggle(data_dir):
    assert gmail.tracking_enabled() is False
    secretstore.set_connection("jev", {"apiKey": "k"})
    assert gmail.tracking_enabled() is False
    _open_gate()
    assert gmail.tracking_enabled() is True


def test_complete_login_ladder(data_dir):
    assert gmail.complete_login("c", "s", None) == "not_enabled"
    _open_gate()
    assert gmail.complete_login(None, None, "access_denied") == "access_denied"
    assert gmail.complete_login(None, "s", None) == "missing_code"
    with patch("truthcv.integrations.connections.auth.gmail.complete_login") as done:
        assert gmail.complete_login("c", "s", None) is None
        done.assert_called_once_with("c", "s")
    from truthcv.integrations.connections.auth import gmail as gmail_auth

    with patch("truthcv.integrations.connections.auth.gmail.complete_login", side_effect=gmail_auth.AuthError("x")):
        assert gmail.complete_login("c", "s", None) == "auth_failed"


def test_status_shape(data_dir):
    assert gmail.status() == {
        "connected": False,
        "email": None,
        "reauth_required": False,
        "tracking_enabled": False,
        "refresh_expires_at": None,
    }
    _open_gate()
    secretstore.set_connection("gmail", {"oauth": {"email": "a@b.c", "reauthRequired": True}})
    assert gmail.status() == {
        "connected": True,
        "email": "a@b.c",
        "reauth_required": True,
        "tracking_enabled": True,
        "refresh_expires_at": None,
    }


# --- job boards ------------------------------------------------------------

def test_job_board_unknown_source_is_not_found(data_dir):
    msg = "'nope' is not an API-backed job board that needs a key."
    for call in (
        lambda: job_boards.key_status("nope"),
        lambda: job_boards.set_key("nope", "k"),
        lambda: job_boards.test_key("nope"),
    ):
        with pytest.raises(NotFound, match="not an API-backed") as exc:
            call()
        assert str(exc.value) == msg


def test_job_board_key_roundtrip(data_dir):
    src = "remoterocketship"
    assert job_boards.key_status(src) == {
        "source": src, "key_set": False, "encryption_available": True,
    }
    assert job_boards.set_key(src, "  abc  ")["key_set"] is True
    assert job_boards.set_key(src, "")["key_set"] is False
    with patch("truthcv.domain.jobfeeds.remoterocketship.check_key", return_value=(True, "ok")) as chk:
        assert job_boards.test_key(src) == (True, "ok")
        chk.assert_called_once()


def test_job_board_set_key_without_encryption_is_bad_request(data_dir, monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    with pytest.raises(BadRequest) as exc:
        job_boards.set_key("remoterocketship", "k")
    assert str(exc.value) == "Set ENCRYPTION_KEY in .env first."


# --- browser ---------------------------------------------------------------

def _resp(payload):
    r = MagicMock()
    r.read.return_value = json.dumps(payload).encode()
    r.__enter__.return_value = r
    return r


def _http_error(code, payload):
    return urllib.error.HTTPError("u", code, "m", {}, io.BytesIO(json.dumps(payload).encode()))


def test_forward_returns_json_and_uses_port_env(monkeypatch):
    monkeypatch.setenv("SESSION_SERVER_PORT", "1234")
    with patch("urllib.request.urlopen", return_value=_resp({"open": False})) as urlopen:
        assert browser.forward_to_session_server("/session") == {"open": False}
    req = urlopen.call_args.args[0]
    assert req.full_url == "http://browser:1234/session"
    assert urlopen.call_args.kwargs["timeout"] == 10


def test_forward_refusal_and_unreachable():
    with patch("urllib.request.urlopen", side_effect=_http_error(409, {"reason": "agent_running"})):
        with pytest.raises(UpstreamRefused) as exc:
            browser.forward_to_session_server("/session", method="POST", body={})
    assert (exc.value.status, exc.value.detail) == (409, {"reason": "agent_running"})
    bad = urllib.error.HTTPError("u", 500, "m", {}, io.BytesIO(b"not json"))
    with patch("urllib.request.urlopen", side_effect=bad):
        with pytest.raises(UpstreamRefused) as exc:
            browser.forward_to_session_server("/session")
    assert exc.value.detail == {"reason": "refused"}
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
        with pytest.raises(Unavailable) as exc:
            browser.forward_to_session_server("/session")
    assert str(exc.value) == "Browser service unreachable"


def test_close_session_clears_blockers_for_session_host():
    replies = [{"open": True, "url": "https://Jobs.Example.com/x"}, {"closed": True}]
    with patch.object(browser, "forward_to_session_server", side_effect=replies), \
         patch("truthcv.services.screenings.clear_login_blockers_for_host", return_value=2) as clear:
        assert browser.close_session() == {
            "closed": True, "closing": False, "reserving": False, "signins_cleared": 2,
        }
    clear.assert_called_once_with("jobs.example.com")


def test_close_session_skips_clearing_when_not_closed_or_no_url():
    for replies in (
        [{"url": "https://a.com"}, {"closed": False}],
        [{}, {"closing": True}],
    ):
        with patch.object(browser, "forward_to_session_server", side_effect=replies), \
             patch("truthcv.services.screenings.clear_login_blockers_for_host") as clear:
            assert browser.close_session()["signins_cleared"] == 0
        clear.assert_not_called()
