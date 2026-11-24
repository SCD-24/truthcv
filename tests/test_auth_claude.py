import time

import httpx
import pytest
import respx
from httpx import Response
from cryptography.fernet import Fernet

import truthcv.infra.secretstore as secretstore
from truthcv.integrations.connections.auth import claude


@pytest.fixture()
def enc(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    return data_dir


def test_constants_match_current_claude_code_flow():
    """Pin the OAuth constants to the flow the current Claude Code CLI uses.

    Verified 2026-08-17 against `claude setup-token` (CLI 2.1.233): the old
    claude.ai/console.anthropic.com endpoints reject logins with
    "Invalid request format"; org:create_api_key is no longer granted.
    """
    assert claude.AUTHORIZE_URL == "https://claude.com/cai/oauth/authorize"
    assert claude.TOKEN_URL == "https://platform.claude.com/v1/oauth/token"
    assert claude.REDIRECT_URI == "https://platform.claude.com/oauth/code/callback"
    assert claude.SCOPES == "user:inference"
    assert claude.CLIENT_ID == "9d1c250a-e61b-44d9-88ed-5944d1962f5e"


def test_start_login_builds_pkce_url(enc):
    out = claude.start_login()
    assert out["flow"] == "paste-code"
    assert out["authUrl"].startswith(claude.AUTHORIZE_URL)
    assert "code_challenge=" in out["authUrl"] and "state=" in out["authUrl"]
    # The claude.com authorize endpoint rejects short state values with
    # "Invalid request format" — 32 random bytes (43 b64url chars) like the
    # Claude Code CLI, verified 2026-08-17.
    state = out["authUrl"].split("state=")[1].split("&")[0]
    assert len(state) == 43


@respx.mock
def test_complete_login_stores_tokens(enc):
    start = claude.start_login()
    state = start["authUrl"].split("state=")[1].split("&")[0]
    respx.post(claude.TOKEN_URL).mock(
        return_value=Response(200, json={
            "access_token": "at-1", "refresh_token": "rt-1",
            "expires_in": 3600, "scope": "user:inference",
        })
    )
    meta = claude.complete_login(f"authcode#{state}")
    rec = secretstore.get_connection("claude")["oauth"]
    assert rec["accessToken"] == "at-1" and rec["refreshToken"] == "rt-1"
    assert "accessToken" not in meta  # metadata only, no secrets


def test_complete_login_rejects_bad_state(enc):
    claude.start_login()
    with pytest.raises(claude.AuthError):
        claude.complete_login("authcode#wrong-state")


@respx.mock
def test_get_valid_token_refreshes_and_keeps_old_refresh_token(enc):
    secretstore.set_connection("claude", {"oauth": {
        "accessToken": "old", "refreshToken": "rt-keep",
        "expiresAt": time.time() + 10, "scope": "", "connectedAt": 0,
    }})
    respx.post(claude.TOKEN_URL).mock(
        return_value=Response(200, json={"access_token": "at-new", "expires_in": 3600})
    )
    assert claude.get_valid_access_token() == "at-new"
    rec = secretstore.get_connection("claude")["oauth"]
    assert rec["refreshToken"] == "rt-keep"  # omitted in response -> preserved


def test_get_valid_token_fresh_skips_refresh(enc):
    secretstore.set_connection("claude", {"oauth": {
        "accessToken": "still-good", "refreshToken": "r",
        "expiresAt": time.time() + 3600, "scope": "", "connectedAt": 0,
    }})
    assert claude.get_valid_access_token() == "still-good"


def _sha(t):
    import hashlib
    return hashlib.sha256(t.encode()).hexdigest()


def _fresh():
    return {"oauth": {
        "accessToken": "cur", "refreshToken": "rt",
        "expiresAt": time.time() + 3600, "scope": "", "connectedAt": 0,
    }, "authMode": "subscription"}


@respx.mock
def test_rejected_sha_match_forces_refresh(enc):
    secretstore.set_connection("claude", _fresh())
    route = respx.post(claude.TOKEN_URL).mock(
        return_value=Response(200, json={"access_token": "at-new", "expires_in": 3600})
    )
    assert claude.get_valid_access_token(_sha("cur")) == "at-new"
    assert route.call_count == 1


@respx.mock
def test_rejected_sha_mismatch_returns_stored_without_http(enc):
    secretstore.set_connection("claude", _fresh())
    route = respx.post(claude.TOKEN_URL).mock(return_value=Response(500))
    assert claude.get_valid_access_token(_sha("other")) == "cur"
    assert route.call_count == 0


@respx.mock
def test_rejected_sha_match_refresh_failure_keeps_credentials(enc):
    existing = _fresh()
    secretstore.set_connection("claude", existing)
    respx.post(claude.TOKEN_URL).mock(return_value=Response(400))
    with pytest.raises(claude.AuthError):
        claude.get_valid_access_token(_sha("cur"))
    assert secretstore.get_connection("claude") == existing


def test_get_valid_token_disconnected_raises(enc):
    with pytest.raises(claude.AuthError):
        claude.get_valid_access_token()


@respx.mock
def test_get_valid_token_wraps_network_error_on_refresh(enc):
    secretstore.set_connection("claude", {"oauth": {
        "accessToken": "old", "refreshToken": "rt-keep",
        "expiresAt": time.time() + 10, "scope": "", "connectedAt": 0,
    }})
    respx.post(claude.TOKEN_URL).mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(claude.AuthError):
        claude.get_valid_access_token()


@respx.mock
def test_complete_login_wraps_network_error_on_exchange(enc):
    start = claude.start_login()
    state = start["authUrl"].split("state=")[1].split("&")[0]
    respx.post(claude.TOKEN_URL).mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(claude.AuthError):
        claude.complete_login(f"authcode#{state}")


def _expiring():
    rec = _fresh()
    rec["oauth"]["expiresAt"] = time.time() + 10
    return rec


@respx.mock
def test_invalid_grant_marks_reauth_required_and_raises_reconnect(enc):
    secretstore.set_connection("claude", _expiring())
    respx.post(claude.TOKEN_URL).mock(return_value=Response(
        400, json={"error": "invalid_grant", "error_description": "Refresh token expired"}))
    with pytest.raises(claude.AuthError) as exc:
        claude.get_valid_access_token()
    assert exc.value.reconnect_required is True
    rec = secretstore.get_connection("claude")["oauth"]
    assert rec["reauthRequired"] is True
    # tokens are kept so logout (which branches on accessToken) keeps working
    assert rec["accessToken"] == "cur" and rec["refreshToken"] == "rt"


@pytest.mark.parametrize("fail", [
    lambda: Response(500, json={"error": "server_error"}),
    lambda: Response(502, text="bad gateway"),
    lambda: httpx.ConnectError("connection refused"),
])
@respx.mock
def test_transient_refresh_failure_does_not_mark(enc, fail):
    existing = _expiring()
    secretstore.set_connection("claude", existing)
    outcome = fail()
    route = respx.post(claude.TOKEN_URL)
    if isinstance(outcome, Response):
        route.mock(return_value=outcome)
    else:
        route.mock(side_effect=outcome)
    with pytest.raises(claude.AuthError) as exc:
        claude.get_valid_access_token()
    assert exc.value.reconnect_required is False
    assert secretstore.get_connection("claude") == existing


@respx.mock
def test_marked_record_short_circuits_without_http(enc):
    marked = _fresh()
    marked["oauth"]["reauthRequired"] = True
    secretstore.set_connection("claude", marked)
    route = respx.post(claude.TOKEN_URL).mock(return_value=Response(200, json={"access_token": "x"}))
    for rejected in (None, _sha("cur"), _sha("other")):
        with pytest.raises(claude.AuthError) as exc:
            claude.get_valid_access_token(rejected)
        assert exc.value.reconnect_required is True
    assert route.call_count == 0


def test_store_record_clears_reauth_flag(enc):
    marked = _fresh()
    marked["oauth"]["reauthRequired"] = True
    secretstore.set_connection("claude", marked)
    claude._store_record({"access_token": "at-new", "refresh_token": "rt-new"})
    assert secretstore.get_connection("claude")["oauth"]["reauthRequired"] is False
