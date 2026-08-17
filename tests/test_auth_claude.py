import time

import httpx
import pytest
import respx
from httpx import Response
from cryptography.fernet import Fernet

import secretstore
from connections.auth import claude


@pytest.fixture()
def enc(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    return data_dir


def test_start_login_builds_pkce_url(enc):
    out = claude.start_login()
    assert out["flow"] == "paste-code"
    assert out["authUrl"].startswith(claude.AUTHORIZE_URL)
    assert "code_challenge=" in out["authUrl"] and "state=" in out["authUrl"]


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
