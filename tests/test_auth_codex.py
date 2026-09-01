"""Tests for connections/auth/codex.py — ChatGPT device-code OAuth flow."""

import base64
import json as _json
import time

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from httpx import Response

import secretstore
from connections.auth import codex


@pytest.fixture()
def enc(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    return data_dir


def _jwt(account_id: str = "acc-1234") -> str:
    """Build a synthetic JWT carrying a chatgpt_account_id claim."""
    payload = {"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}
    payload_b64 = (
        base64.urlsafe_b64encode(_json.dumps(payload).encode())
        .rstrip(b"=").decode()
    )
    return f"header.{payload_b64}.sig"


def test_constants_match_openai_device_flow():
    """Pin the OAuth constants to the flow the Codex CLI uses."""
    assert codex.CLIENT_ID == "app_EMoamEEZ73f0CkXaXp7hrann"
    assert codex.USERCODE_URL == "https://auth.openai.com/api/accounts/deviceauth/usercode"
    assert codex.DEVICE_TOKEN_URL == "https://auth.openai.com/api/accounts/deviceauth/token"
    assert codex.TOKEN_URL == "https://auth.openai.com/oauth/token"
    assert codex.VERIFICATION_URI == "https://auth.openai.com/codex/device"
    assert codex.DEVICE_REDIRECT_URI == "https://auth.openai.com/deviceauth/callback"


@respx.mock
def test_start_login_returns_device_code_shape(enc):
    """start_login posts EXACTLY {client_id} to USERCODE_URL and returns the documented fields."""
    respx.post(codex.USERCODE_URL).mock(
        return_value=Response(200, json={
            "device_auth_id": "dev-1",
            "user_code": "ABCD-EFGH",
            "interval": 5,
            "expires_in": 900,
        })
    )
    out = codex.start_login()
    assert out["flow"] == "device-code"
    assert out["userCode"] == "ABCD-EFGH"
    assert out["verificationUri"] == codex.VERIFICATION_URI
    assert out["intervalSeconds"] == 5
    assert out["expiresInSeconds"] == 900


@respx.mock
def test_start_login_accepts_string_interval(enc):
    respx.post(codex.USERCODE_URL).mock(
        return_value=Response(200, json={
            "device_auth_id": "dev-2",
            "user_code": "WXYZ",
            "interval": "7",  # numeric string
        })
    )
    out = codex.start_login()
    assert out["intervalSeconds"] == 7


@respx.mock
def test_start_login_coerces_zero_or_negative_interval_to_default(enc):
    respx.post(codex.USERCODE_URL).mock(
        return_value=Response(200, json={
            "device_auth_id": "dev-3",
            "user_code": "LOW",
            "interval": 0,
        })
    )
    out = codex.start_login()
    assert out["intervalSeconds"] == 5


@respx.mock
def test_start_login_404_means_device_login_disabled(enc):
    respx.post(codex.USERCODE_URL).mock(return_value=Response(404))
    with pytest.raises(codex.AuthError) as exc:
        codex.start_login()
    assert "device login" in str(exc.value).lower()


@respx.mock
def test_poll_login_returns_pending_on_403_or_404(enc):
    # Mock BOTH the start and the poll so respx tracks them all in this block
    respx.post(codex.USERCODE_URL).mock(
        return_value=Response(200, json={"device_auth_id": "dev-4", "user_code": "X", "interval": 5})
    )
    respx.post(codex.DEVICE_TOKEN_URL).mock(return_value=Response(403))
    codex.start_login()
    assert codex.poll_login() == {"status": "pending"}

    respx.post(codex.DEVICE_TOKEN_URL).mock(return_value=Response(404))
    assert codex.poll_login() == {"status": "pending"}


@respx.mock
def test_poll_login_returns_pending_on_deviceauth_authorization_pending(enc):
    respx.post(codex.USERCODE_URL).mock(
        return_value=Response(200, json={"device_auth_id": "dev-5", "user_code": "Y", "interval": 5})
    )
    respx.post(codex.DEVICE_TOKEN_URL).mock(
        return_value=Response(400, json={"error": {"code": "deviceauth_authorization_pending"}})
    )
    codex.start_login()
    assert codex.poll_login() == {"status": "pending"}


@respx.mock
def test_poll_login_slow_down_bumps_interval_by_5(enc):
    respx.post(codex.USERCODE_URL).mock(
        return_value=Response(200, json={"device_auth_id": "dev-6", "user_code": "Z", "interval": 5})
    )
    respx.post(codex.DEVICE_TOKEN_URL).mock(
        return_value=Response(400, json={"error": {"code": "slow_down"}})
    )
    codex.start_login()
    out = codex.poll_login()
    assert out == {"status": "pending", "intervalSeconds": 10}


@respx.mock
def test_poll_login_successful_exchanges_token_form_encoded(enc):
    respx.post(codex.USERCODE_URL).mock(
        return_value=Response(200, json={"device_auth_id": "dev-7", "user_code": "T", "interval": 5})
    )
    respx.post(codex.DEVICE_TOKEN_URL).mock(
        return_value=Response(200, json={
            "authorization_code": "auth-code-xyz",
            "code_verifier": "verifier-123",
        })
    )
    token_route = respx.post(codex.TOKEN_URL).mock(
        return_value=Response(200, json={
            "access_token": "at-new",
            "refresh_token": "rt-new",
            "expires_in": 3600,
            "scope": "openid profile",
        })
    )
    codex.start_login()
    out = codex.poll_login()
    assert out["status"] == "complete"
    # Verify form-encoded body (URL-encoded)
    request = token_route.calls.last.request
    body = request.read().decode()
    assert "grant_type=authorization_code" in body
    assert "code=auth-code-xyz" in body
    assert "code_verifier=verifier-123" in body
    # redirect_uri is URL-encoded
    assert "redirect_uri=https%3A%2F%2Fauth.openai.com%2Fdeviceauth%2Fcallback" in body
    assert f"client_id={codex.CLIENT_ID}" in body
    # oauth record stored with subscription authMode
    rec = secretstore.get_connection("codex")["oauth"]
    assert rec["accessToken"] == "at-new"
    assert rec["refreshToken"] == "rt-new"
    assert secretstore.get_connection("codex")["authMode"] == "subscription"


@respx.mock
def test_poll_login_after_deadline_raises(enc):
    respx.post(codex.USERCODE_URL).mock(
        return_value=Response(200, json={"device_auth_id": "dev-8", "user_code": "E", "interval": 5})
    )
    codex.start_login()
    codex._pending = {"deviceAuthId": "x", "userCode": "y", "interval": 5, "deadline": 0}
    with pytest.raises(codex.AuthError):
        codex.poll_login()


@respx.mock
def test_poll_login_without_pending_raises(enc):
    codex._pending = None
    with pytest.raises(codex.AuthError):
        codex.poll_login()


@respx.mock
def test_get_valid_access_token_returns_cached_when_fresh(enc):
    secretstore.set_connection("codex", {"oauth": {
        "accessToken": "cached", "refreshToken": "rt",
        "expiresAt": time.time() + 3600, "scope": "", "connectedAt": 0,
    }})
    assert codex.get_valid_access_token() == "cached"


@respx.mock
def test_get_valid_access_token_refreshes_when_near_expiry(enc):
    secretstore.set_connection("codex", {"oauth": {
        "accessToken": "old", "refreshToken": "rt-keep",
        "expiresAt": time.time() + 10, "scope": "", "connectedAt": 0,
    }})
    refresh_route = respx.post(codex.TOKEN_URL).mock(
        return_value=Response(200, json={"access_token": "new-at", "expires_in": 3600})
    )
    assert codex.get_valid_access_token() == "new-at"
    body = refresh_route.calls.last.request.read().decode()
    assert "grant_type=refresh_token" in body
    assert "refresh_token=rt-keep" in body
    assert f"client_id={codex.CLIENT_ID}" in body
    # refresh_token preserved when absent from response
    rec = secretstore.get_connection("codex")["oauth"]
    assert rec["refreshToken"] == "rt-keep"


def test_account_id_decodes_jwt_payload():
    token = _jwt("acct-test-1")
    assert codex.account_id(token) == "acct-test-1"


def test_account_id_returns_empty_for_malformed_token():
    assert codex.account_id("not.a.jwt") == ""
    assert codex.account_id("onlyonepart") == ""
    assert codex.account_id("") == ""
