"""HTTP client for the browser/session-server.js control server, and session close.

Lives in services so the attended-session routes only shape the response; it
raises ``services.errors`` types instead of ``HTTPException`` and the global
handler maps them back to the same statuses.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

from services import screenings as _screenings
from services.errors import Unavailable, UpstreamRefused


def _browser_control_url(path: str) -> str:
    """Build the session-server control URL from env, defaulting port 8932."""
    port = os.environ.get("SESSION_SERVER_PORT", "8932")
    return f"http://browser:{port}{path}"


def forward_to_session_server(path: str, method: str = "GET", body: dict | None = None) -> dict:
    """Forward a request to browser/session-server.js.

    Distinguishes three outcomes the UI must tell apart: a normal answer, a
    refusal the session server made deliberately (4xx/503 — raised as
    UpstreamRefused with its own status so "the agent is applying right now"
    does not read as "the browser is broken"), and the container being
    unreachable (Unavailable, 503).
    """
    token = os.environ.get("AGENT_API_TOKEN", "")
    data = json.dumps(body or {}).encode() if method == "POST" else None
    req = urllib.request.Request(
        _browser_control_url(path),
        method=method,
        headers={"X-Agent-Token": token, "Content-Type": "application/json"},
        data=data,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        # Forward the session server's own refusal payload. It distinguishes
        # session_open (which carries the already-open session's URL, so the UI
        # can offer to return to it) from agent_running and profile_busy — all
        # three are 409s that call for different words on screen.
        try:
            detail = json.loads(exc.read())
        except (ValueError, OSError):
            detail = {"reason": "refused"}
        raise UpstreamRefused(exc.code, detail) from exc
    except urllib.error.URLError as exc:
        raise Unavailable("Browser service unreachable") from exc


def _host_of(url: str) -> str:
    """The full host of an absolute http(s) URL, or "" if it is not one.

    Same rule as api/routes.py's _host_of: anything without a scheme and a
    netloc is not addressable, so it cannot be a sign-in destination.
    """
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return parsed.netloc.casefold()


def close_session() -> dict:
    """Close the attended session and release the browser.

    Exists so the route only shapes the response. When closing a session,
    re-arm any login-blocked items whose host matches the closed session's URL,
    so they re-enter the queue for the next run. Returns closed, closing,
    reserving and signins_cleared.
    """
    # Read the current session URL before closing it
    session_data = forward_to_session_server("/session")
    session_url = session_data.get("url", "")

    # Forward the close request
    data = forward_to_session_server("/session/close", method="POST")

    signins_cleared = 0
    # Only clear blockers if the session existed and the close was accepted
    if session_url and (data.get("closed", False) or data.get("closing", False)):
        # Clear login blockers for this host
        host = _host_of(session_url)
        if host:
            signins_cleared = _screenings.clear_login_blockers_for_host(host)

    return {
        "closed": data.get("closed", False),
        "closing": data.get("closing", False),
        "reserving": data.get("reserving", False),
        "signins_cleared": signins_cleared,
    }
