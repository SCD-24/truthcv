"""Gmail OAuth helpers and lazy access-token refresh.

Uses Google's standard browser redirect flow with offline access so the app can
read Gmail later without keeping browser-visible tokens anywhere.
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
import time
from urllib.parse import urlencode

import httpx

from secretstore import get_connection, set_connection

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_EXPIRY_SKEW_S = 300


class AuthError(RuntimeError):
    """Login/refresh failed or Gmail needs to be reconnected."""

    def __init__(self, message: str, *, reconnect_required: bool = False) -> None:
        super().__init__(message)
        self.reconnect_required = reconnect_required


_pending: dict[str, dict[str, str]] = {}
_refresh_lock = threading.Lock()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _client_id() -> str:
    return os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()


def _client_secret() -> str:
    return os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()


def _require_client_config() -> tuple[str, str]:
    client_id = _client_id()
    client_secret = _client_secret()
    if not client_id or not client_secret:
        raise AuthError("Google OAuth is not configured on the server.")
    return client_id, client_secret


def start_login(redirect_uri: str) -> dict:
    client_id, _ = _require_client_config()
    verifier = _b64url(os.urandom(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = _b64url(os.urandom(32))
    _pending[state] = {"verifier": verifier, "redirect_uri": redirect_uri}
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return {"flow": "browser", "authUrl": f"{AUTHORIZE_URL}?{query}"}


def _gmail_profile(access_token: str) -> dict:
    try:
        resp = httpx.get(
            PROFILE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise AuthError("Could not read the connected Gmail profile.") from exc
    if resp.status_code != 200:
        raise AuthError("Could not read the connected Gmail profile.")
    return resp.json()


def _store_record(
    payload: dict,
    *,
    email: str,
    old_refresh: str | None = None,
    connected_at: float | None = None,
) -> dict:
    now = time.time()
    record = {
        "accessToken": payload["access_token"],
        "refreshToken": payload.get("refresh_token") or old_refresh or "",
        "expiresAt": now + float(payload.get("expires_in", 3600)),
        "scope": payload.get("scope", SCOPE),
        "connectedAt": connected_at or now,
        "email": email,
        "reauthRequired": False,
    }
    set_connection("gmail", {"oauth": record, "authMode": "subscription"})
    return record


def complete_login(code: str, state: str) -> dict:
    pending = _pending.pop(state, None)
    if pending is None:
        raise AuthError("This Gmail sign-in link is no longer valid. Start again.")
    client_id, client_secret = _require_client_config()
    try:
        resp = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": pending["redirect_uri"],
                "code_verifier": pending["verifier"],
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise AuthError("Token exchange failed — could not reach Google OAuth.") from exc
    if resp.status_code != 200:
        raise AuthError(f"Token exchange failed ({resp.status_code}).")
    payload = resp.json()
    email = _gmail_profile(payload["access_token"]).get("emailAddress", "")
    return _store_record(payload, email=email)


def mark_reconnect_required() -> None:
    conn = get_connection("gmail")
    oauth = dict(conn.get("oauth") or {})
    if not oauth:
        return
    oauth.update(
        {
            "accessToken": "",
            "refreshToken": "",
            "expiresAt": 0,
            "reauthRequired": True,
        }
    )
    set_connection("gmail", {"oauth": oauth, "authMode": "subscription"})


def get_valid_access_token() -> str:
    client_id, client_secret = _require_client_config()
    with _refresh_lock:
        record = get_connection("gmail").get("oauth") or {}
        if record.get("reauthRequired"):
            raise AuthError(
                "Gmail access was revoked or expired — reconnect Gmail in Settings.",
                reconnect_required=True,
            )
        if not record.get("accessToken"):
            raise AuthError("Gmail is not connected.")
        if record.get("expiresAt", 0) - time.time() > _EXPIRY_SKEW_S:
            return record["accessToken"]
        try:
            resp = httpx.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": record.get("refreshToken", ""),
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise AuthError("Gmail token refresh failed — try again later.") from exc
        if resp.status_code != 200:
            mark_reconnect_required()
            raise AuthError(
                "Gmail access was revoked or expired — reconnect Gmail in Settings.",
                reconnect_required=True,
            )
        refreshed = _store_record(
            resp.json(),
            email=record.get("email", ""),
            old_refresh=record.get("refreshToken"),
            connected_at=record.get("connectedAt"),
        )
        return refreshed["accessToken"]
