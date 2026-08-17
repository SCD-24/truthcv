"""Claude Pro/Max subscription OAuth (PKCE paste-code flow).

Ported from aether server/auth/claude.js. Reuses Claude Code's public OAuth
client. NOTE: undocumented by Anthropic and ToS-gray; subscription tokens
additionally require the Claude Code system preamble on every API call.
Pending PKCE state lives in module memory only — never persisted, never
sent to the client.
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
import time
from urllib.parse import urlencode

import httpx

# Verify every constant against aether server/auth/claude.js when porting.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPES = "org:create_api_key user:profile user:inference"
CLAUDE_CODE_PREAMBLE = "You are Claude Code, Anthropic's official CLI for Claude."

_EXPIRY_SKEW_S = 300


class AuthError(RuntimeError):
    """Login/refresh failed or the connection is absent."""


_pending: dict | None = None
_refresh_lock = threading.Lock()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def start_login() -> dict:
    global _pending
    verifier = _b64url(os.urandom(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = _b64url(os.urandom(16))
    _pending = {"verifier": verifier, "state": state}
    query = urlencode({
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return {"flow": "paste-code", "authUrl": f"{AUTHORIZE_URL}?{query}"}


def _store_record(payload: dict, old_refresh: str | None = None) -> dict:
    from secretstore import set_connection

    record = {
        "accessToken": payload["access_token"],
        "refreshToken": payload.get("refresh_token") or old_refresh or "",
        "expiresAt": time.time() + float(payload.get("expires_in", 3600)),
        "scope": payload.get("scope", ""),
        "connectedAt": time.time(),
    }
    set_connection("claude", {"oauth": record, "authMode": "subscription"})
    return record


def complete_login(code_state: str) -> dict:
    global _pending
    if _pending is None:
        raise AuthError("No login in progress. Start again.")
    code, _, state = code_state.strip().partition("#")
    if not code or state != _pending["state"]:
        raise AuthError("Pasted code doesn't match this login attempt. Start again.")
    try:
        resp = httpx.post(TOKEN_URL, json={
            "grant_type": "authorization_code",
            "code": code,
            "state": state,
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": _pending["verifier"],
        }, timeout=30)
    except httpx.HTTPError as exc:
        _pending = None
        raise AuthError("Token exchange failed — could not reach the Claude OAuth server.") from exc
    _pending = None
    if resp.status_code != 200:
        raise AuthError(f"Token exchange failed ({resp.status_code}).")
    record = _store_record(resp.json())
    return {"connectedAt": record["connectedAt"], "expiresAt": record["expiresAt"], "scope": record["scope"]}


def get_valid_access_token() -> str:
    from secretstore import get_connection

    with _refresh_lock:
        record = get_connection("claude").get("oauth")
        if not record or not record.get("accessToken"):
            raise AuthError("Claude subscription is not connected.")
        if record.get("expiresAt", 0) - time.time() > _EXPIRY_SKEW_S:
            return record["accessToken"]
        try:
            resp = httpx.post(TOKEN_URL, json={
                "grant_type": "refresh_token",
                "refresh_token": record.get("refreshToken", ""),
                "client_id": CLIENT_ID,
            }, timeout=30)
        except httpx.HTTPError as exc:
            raise AuthError("Claude token refresh failed — reconnect the subscription in Settings.") from exc
        if resp.status_code != 200:
            raise AuthError("Claude token refresh failed — reconnect the subscription in Settings.")
        return _store_record(resp.json(), old_refresh=record.get("refreshToken"))["accessToken"]
