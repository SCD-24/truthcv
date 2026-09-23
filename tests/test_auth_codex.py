"""Tests for connections/auth/codex.py — ChatGPT device-code OAuth flow."""

import base64
import json as _json
import time
from urllib.parse import parse_qs

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


def _use_transport(monkeypatch, handler):
    """Route the module's top-level httpx.post calls through a real encoder."""
    transport = httpx.MockTransport(handler)

    def post(url, **kwargs):
        with httpx.Client(transport=transport) as client:
            return client.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", post)


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


def test_poll_login_successful_exchanges_token_form_encoded(enc, monkeypatch):
    auth_code = "auth+code/&= ?%"
    verifier = "verifier+/&= ?%"
    token_requests = []

    def handler(request):
        if str(request.url) == codex.USERCODE_URL:
            return Response(200, json={"device_auth_id": "dev-7", "user_code": "T", "interval": 5})
        if str(request.url) == codex.DEVICE_TOKEN_URL:
            return Response(200, json={"authorization_code": auth_code, "code_verifier": verifier})
        assert str(request.url) == codex.TOKEN_URL
        token_requests.append(request)
        return Response(200, json={
            "access_token": "at-new", "refresh_token": "rt-new",
            "expires_in": 3600, "scope": "openid profile",
        })

    _use_transport(monkeypatch, handler)
    codex.start_login()
    out = codex.poll_login()
    assert out["status"] == "complete"
    assert len(token_requests) == 1
    request = token_requests[0]
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert parse_qs(request.content.decode()) == {
        "grant_type": ["authorization_code"],
        "client_id": [codex.CLIENT_ID],
        "code": [auth_code],
        "code_verifier": [verifier],
        "redirect_uri": [codex.DEVICE_REDIRECT_URI],
    }
    # Subscription credentials are persisted encrypted, not leaked as plaintext.
    rec = secretstore.get_connection("codex")["oauth"]
    assert rec["accessToken"] == "at-new"
    assert rec["refreshToken"] == "rt-new"
    assert secretstore.get_connection("codex")["authMode"] == "subscription"
    assert b"at-new" not in (enc / "secrets.enc").read_bytes()


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


def test_get_valid_access_token_refreshes_when_near_expiry(enc, monkeypatch):
    refresh_token = "rt+keep/&= ?%"
    secretstore.set_connection("codex", {"oauth": {
        "accessToken": "old", "refreshToken": refresh_token,
        "expiresAt": time.time() + 10, "scope": "", "connectedAt": 0,
    }})
    requests = []

    def handler(request):
        assert str(request.url) == codex.TOKEN_URL
        requests.append(request)
        return Response(200, json={"access_token": "new-at", "expires_in": 3600})

    _use_transport(monkeypatch, handler)
    assert codex.get_valid_access_token() == "new-at"
    assert len(requests) == 1
    request = requests[0]
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert parse_qs(request.content.decode()) == {
        "grant_type": ["refresh_token"],
        "refresh_token": [refresh_token],
        "client_id": [codex.CLIENT_ID],
    }
    # refresh_token preserved when absent from response, still encrypted on disk
    rec = secretstore.get_connection("codex")["oauth"]
    assert rec["refreshToken"] == refresh_token
    assert rec["accessToken"] == "new-at"
    assert b"new-at" not in (enc / "secrets.enc").read_bytes()


def test_failed_code_exchange_preserves_stored_credentials(enc, monkeypatch):
    existing = {"oauth": {
        "accessToken": "existing", "refreshToken": "existing-refresh",
        "expiresAt": time.time() + 3600, "scope": "old", "connectedAt": 0,
    }, "authMode": "subscription"}
    secretstore.set_connection("codex", existing)
    encrypted = (enc / "secrets.enc").read_bytes()

    def handler(request):
        if str(request.url) == codex.USERCODE_URL:
            return Response(200, json={"device_auth_id": "dev-fail", "user_code": "F"})
        if str(request.url) == codex.DEVICE_TOKEN_URL:
            return Response(200, json={"authorization_code": "code", "code_verifier": "verifier"})
        assert str(request.url) == codex.TOKEN_URL
        return Response(400, json={"error": "invalid_grant"})

    _use_transport(monkeypatch, handler)
    codex.start_login()
    with pytest.raises(codex.AuthError, match=r"Token exchange failed \(400\)"):
        codex.poll_login()
    assert secretstore.get_connection("codex") == existing
    assert (enc / "secrets.enc").read_bytes() == encrypted


def test_failed_refresh_preserves_stored_credentials(enc, monkeypatch):
    existing = {"oauth": {
        "accessToken": "existing", "refreshToken": "existing-refresh",
        "expiresAt": time.time() + 10, "scope": "old", "connectedAt": 0,
    }, "authMode": "subscription"}
    secretstore.set_connection("codex", existing)
    encrypted = (enc / "secrets.enc").read_bytes()

    def handler(request):
        assert str(request.url) == codex.TOKEN_URL
        return Response(400, json={"error": "invalid_grant"})

    _use_transport(monkeypatch, handler)
    with pytest.raises(codex.AuthError, match="ChatGPT token refresh failed"):
        codex.get_valid_access_token()
    assert secretstore.get_connection("codex") == existing
    assert (enc / "secrets.enc").read_bytes() == encrypted


def test_account_id_decodes_jwt_payload():
    token = _jwt("acct-test-1")
    assert codex.account_id(token) == "acct-test-1"


def test_account_id_returns_empty_for_malformed_token():
    assert codex.account_id("not.a.jwt") == ""
    assert codex.account_id("onlyonepart") == ""
    assert codex.account_id("") == ""
