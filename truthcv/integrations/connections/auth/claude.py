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

# Constants mirror the current Claude Code CLI's manual (paste-code) flow —
# verified against `claude setup-token` output. The endpoints aether used
# (claude.ai/console.anthropic.com, org:create_api_key scope) are rejected
# with "Invalid request format" since the claude.com migration.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.com/cai/oauth/authorize"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
SCOPES = "user:inference"
CLAUDE_CODE_PREAMBLE = "You are Claude Code, Anthropic's official CLI for Claude."

_EXPIRY_SKEW_S = 300
_INVALID_GRANT = "invalid_grant"
_RECONNECT_MSG = "Claude token refresh failed — reconnect the subscription in Settings."


class AuthError(RuntimeError):
    """Login/refresh failed or the connection is absent."""

    def __init__(self, message: str, *, reconnect_required: bool = False) -> None:
        super().__init__(message)
        self.reconnect_required = reconnect_required


_pending: dict | None = None
_refresh_lock = threading.Lock()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def start_login() -> dict:
    global _pending
    verifier = _b64url(os.urandom(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    # 32 bytes, like the Claude Code CLI — the claude.com authorize endpoint
    # rejects shorter state values with "Invalid request format".
    state = _b64url(os.urandom(32))
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
    from truthcv.infra.secretstore import set_connection

    record = {
        "accessToken": payload["access_token"],
        "refreshToken": payload.get("refresh_token") or old_refresh or "",
        "expiresAt": time.time() + float(payload.get("expires_in", 3600)),
        "scope": payload.get("scope", ""),
        "connectedAt": time.time(),
        "reauthRequired": False,
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


def _refresh_error_code(resp: httpx.Response) -> str:
    """OAuth ``error`` code from a failed refresh, or "" if the body has none."""
    try:
        body = resp.json()
    except ValueError:
        return ""
    code = body.get("error") if isinstance(body, dict) else None
    return code if isinstance(code, str) else ""


def _raise_refresh_failure(resp: httpx.Response, record: dict) -> None:
    """Classify a non-200 refresh answer and raise the matching AuthError.

    Only ``invalid_grant`` means the refresh token is dead, so only it marks the
    record as needing reconnection (tokens are kept so logout still works).
    Anything else (5xx, 429, other 4xx, non-JSON) is transient and leaves the
    stored record untouched.
    """
    from truthcv.infra.secretstore import set_connection

    if _refresh_error_code(resp) == _INVALID_GRANT:
        set_connection("claude", {"oauth": {**record, "reauthRequired": True}})
        raise AuthError(_RECONNECT_MSG, reconnect_required=True)
    raise AuthError("Claude token refresh failed — try again later.")


def get_valid_access_token(rejected_sha256: str | None = None) -> str:
    """Return a valid claude access token, refreshing if near expiry.

    rejected_sha256: sha256 hexdigest of an access token the upstream rejected.
    If the stored token differs, it is returned without refreshing; if it
    matches, a refresh is forced even when the token looks fresh.
    """
    from truthcv.infra.secretstore import get_connection

    with _refresh_lock:
        record = get_connection("claude").get("oauth")
        if record and record.get("reauthRequired"):
            raise AuthError(_RECONNECT_MSG, reconnect_required=True)
        if not record or not record.get("accessToken"):
            raise AuthError("Claude subscription is not connected.")
        force = False
        if rejected_sha256 is not None:
            current = hashlib.sha256(record["accessToken"].encode()).hexdigest()
            if rejected_sha256 != current:
                return record["accessToken"]
            force = True
        if not force and record.get("expiresAt", 0) - time.time() > _EXPIRY_SKEW_S:
            return record["accessToken"]
        try:
            resp = httpx.post(TOKEN_URL, json={
                "grant_type": "refresh_token",
                "refresh_token": record.get("refreshToken", ""),
                "client_id": CLIENT_ID,
                "scope": SCOPES,
            }, timeout=30)
        except httpx.HTTPError as exc:
            raise AuthError("Claude token refresh failed — try again later.") from exc
        if resp.status_code != 200:
            _raise_refresh_failure(resp, record)
        return _store_record(resp.json(), old_refresh=record.get("refreshToken"))["accessToken"]
