"""ChatGPT (Codex) subscription OAuth (device-code flow).

Uses OpenAI's official device-code flow, reusing the Codex CLI's public
CLIENT_ID. Pending device-code state lives in module memory only — never
persisted, never sent to the client.
"""

from __future__ import annotations

import base64
import json as _json
import threading
import time
from urllib.parse import urlencode

import httpx

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
USERCODE_URL = "https://auth.openai.com/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = "https://auth.openai.com/api/accounts/deviceauth/token"
TOKEN_URL = "https://auth.openai.com/oauth/token"
VERIFICATION_URI = "https://auth.openai.com/codex/device"
DEVICE_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback"
DEVICE_TIMEOUT_S = 900
_EXPIRY_SKEW_S = 300


class AuthError(RuntimeError):
    """Login/refresh failed or the connection is absent."""


_pending: dict | None = None
_refresh_lock = threading.Lock()


def account_id(access_token: str) -> str:
    """Extract chatgpt_account_id from JWT payload via base64url decode of segment [1]."""
    try:
        parts = access_token.split(".")
        if len(parts) < 2:
            return ""
        payload_b64 = parts[1]
        # Pad to a multiple of 4 for base64 decode
        padding = 4 - (len(payload_b64) % 4)
        if padding < 4:
            payload_b64 += "=" * padding
        payload = _json.loads(base64.urlsafe_b64decode(payload_b64))
        auth_data = payload.get("https://api.openai.com/auth", {})
        return auth_data.get("chatgpt_account_id", "") or ""
    except Exception:
        return ""


def _parse_interval(value: float | str | None) -> float:
    """Coerce interval to a positive finite float, defaulting to 5."""
    if value is None:
        return 5.0
    try:
        f = float(str(value).strip())
    except (ValueError, TypeError):
        return 5.0
    if f <= 0 or not (f < float("inf")):
        return 5.0
    return f


def _store_record(payload: dict, old_refresh: str | None = None) -> dict:
    """Persist an OAuth token record to secretstore under the codex card."""
    from secretstore import set_connection

    record = {
        "accessToken": payload["access_token"],
        "refreshToken": payload.get("refresh_token") or old_refresh or "",
        "expiresAt": time.time() + float(payload.get("expires_in", 3600)),
        "scope": payload.get("scope", ""),
        "connectedAt": time.time(),
    }
    set_connection("codex", {"oauth": record, "authMode": "subscription"})
    return record


def start_login() -> dict:
    """Initiate the device-code flow; return user code and verification URI.

    The server generates its own PKCE pair — we send only client_id.
    Raises AuthError on HTTP 404 (device login not enabled for this account).
    """
    global _pending

    resp = httpx.post(USERCODE_URL, json={"client_id": CLIENT_ID}, timeout=30)
    if resp.status_code == 404:
        raise AuthError("Device login is not enabled for this account.")
    resp.raise_for_status()

    body = resp.json()
    device_auth_id = body["device_auth_id"]
    user_code = body["user_code"]
    interval = _parse_interval(body.get("interval"))
    deadline = time.time() + DEVICE_TIMEOUT_S

    _pending = {
        "deviceAuthId": device_auth_id,
        "userCode": user_code,
        "interval": interval,
        "deadline": deadline,
    }

    return {
        "flow": "device-code",
        "userCode": user_code,
        "verificationUri": VERIFICATION_URI,
        "intervalSeconds": interval,
        "expiresInSeconds": DEVICE_TIMEOUT_S,
    }


def _exchange_code(auth_code: str, code_verifier: str) -> dict:
    """Exchange an authorization code for tokens via the token URL."""
    resp = httpx.post(
        TOKEN_URL,
        data=urlencode({
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": auth_code,
            "code_verifier": code_verifier,
            "redirect_uri": DEVICE_REDIRECT_URI,
        }),
        timeout=30,
    )
    if resp.status_code != 200:
        raise AuthError(f"Token exchange failed ({resp.status_code}).")
    return resp.json()


def poll_login() -> dict:
    """Poll the device-token endpoint once; frontend drives cadence.

    Raises AuthError if no login is pending or the deadline has passed.
    On a successful completion poll, immediately exchanges the code for tokens.
    """
    global _pending

    if _pending is None:
        raise AuthError("No login in progress. Start again.")

    if time.time() > _pending["deadline"]:
        raise AuthError("Device code expired. Start again.")

    resp = httpx.post(
        DEVICE_TOKEN_URL,
        json={
            "device_auth_id": _pending["deviceAuthId"],
            "user_code": _pending["userCode"],
        },
        timeout=30,
    )

    # Still waiting
    if resp.status_code in (403, 404):
        return {"status": "pending"}

    # Completed
    if resp.status_code // 100 == 2:
        body = resp.json()
        auth_code = body.get("authorization_code")
        code_verifier = body.get("code_verifier")
        if not auth_code or not code_verifier:
            raise AuthError("Incomplete device authorization response.")
        record = _store_record(_exchange_code(auth_code, code_verifier))
        _pending = None
        return {
            "status": "complete",
            "connectedAt": record["connectedAt"],
            "expiresAt": record["expiresAt"],
            "scope": record["scope"],
        }

    # Other HTTP status — read error from body
    try:
        body = resp.json()
    except Exception:
        body = {}
    error_info = body.get("error", {})
    if isinstance(error_info, dict):
        error_code = error_info.get("code", error_info)
    else:
        error_code = error_info

    if error_code == "deviceauth_authorization_pending":
        return {"status": "pending"}
    if error_code == "slow_down":
        new_interval = _pending["interval"] + 5
        _pending["interval"] = new_interval
        return {"status": "pending", "intervalSeconds": new_interval}

    raise AuthError(f"Device auth error: {error_code}")


def get_valid_access_token() -> str:
    """Return a valid codex access token, refreshing if within 300 s of expiry."""
    from secretstore import get_connection

    with _refresh_lock:
        record = get_connection("codex").get("oauth")
        if not record or not record.get("accessToken"):
            raise AuthError("ChatGPT subscription is not connected.")

        if record.get("expiresAt", 0) - time.time() > _EXPIRY_SKEW_S:
            return record["accessToken"]

        try:
            resp = httpx.post(
                TOKEN_URL,
                data=urlencode({
                    "grant_type": "refresh_token",
                    "refresh_token": record.get("refreshToken", ""),
                    "client_id": CLIENT_ID,
                }),
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise AuthError(
                "ChatGPT token refresh failed — reconnect the subscription in Settings."
            ) from exc

        if resp.status_code != 200:
            raise AuthError(
                "ChatGPT token refresh failed — reconnect the subscription in Settings."
            )

        return _store_record(
            resp.json(), old_refresh=record.get("refreshToken")
        )["accessToken"]
