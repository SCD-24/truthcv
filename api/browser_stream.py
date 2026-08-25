"""Relay the browser container's noVNC WebSocket through the app.

The `browser` service's noVNC port is not published: the operator reaches the
viewport through this route instead, so there is one address and one place to
guard rather than a second passwordless port on every interface.

That guard is two checks, both run before `websocket.accept()`:

- `peer_allowed` requires the TCP peer to be loopback. Origin and Host are
  both set by the client, so a non-browser caller — including another
  container on the compose network — can simply send whatever it wants for
  either. The peer address is the one signal it cannot forge.
- `origin_allowed` requires the Origin header to match Host and to be a
  loopback (or explicitly allowed) hostname, defending the browser-reachable
  path: WebSocket handshakes are exempt from the same-origin policy and the
  CORS middleware in `api/main.py` does not see them, so without this check
  any page the operator visits while a session is open could open this
  socket and drive a browser holding their live sessions.
"""

from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import urlparse

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

# Hostnames a legitimate viewer can reach this app on. The app binds to
# loopback, so anything else is either a misconfiguration or a DNS-rebinding
# attack: an attacker domain resolving to 127.0.0.1 sends a Host header that
# matches its own Origin, which makes an Origin-vs-Host comparison agree with
# itself. Mirrors the --allowed-hosts defence browser/entrypoint.sh already
# applies to @playwright/mcp for the same reason. `peer_allowed` below is the
# defence that keeps this list safe to widen: even a widened hostname still
# requires the caller to actually be on loopback.
_LOOPBACK_HOSTNAMES = frozenset(
    {"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1", "::ffff:127.0.0.1"}
)

# The one signal a caller cannot forge. Origin and Host are both set by the
# client; uvicorn fills scope["client"] from the accepted socket. Without
# `peer_allowed`, any process that can route to the app port — including
# another container on the compose network — gets keyboard and mouse control
# of a browser holding the operator's live sessions, with two headers and no
# credential.
_LOOPBACK_PEERS = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})

_logged_extra_hosts = False


def allowed_origin_hostnames() -> frozenset[str]:
    """Loopback by default; extend via BROWSER_STREAM_ALLOWED_HOSTS (comma-separated)
    for a deployment that deliberately publishes the app beyond loopback.

    Globs are not supported: an entry is matched exactly, case-insensitively.
    """
    global _logged_extra_hosts
    extra = os.environ.get("BROWSER_STREAM_ALLOWED_HOSTS", "")
    names = {h.strip().casefold() for h in extra.split(",") if h.strip()}
    if names and not _logged_extra_hosts:
        # Logged once so a widened, rebinding-adjacent configuration is
        # visible in the logs rather than a silent change in trust boundary.
        logger.warning(
            "BROWSER_STREAM_ALLOWED_HOSTS widens the browser-stream Origin allowlist "
            "beyond loopback: %s",
            sorted(names),
        )
        _logged_extra_hosts = True
    return frozenset(_LOOPBACK_HOSTNAMES | names)


def peer_allowed(peer: str) -> bool:
    """True when `peer` (the TCP client address) is loopback.

    Unlike Origin and Host, the client address is filled in by uvicorn from
    the accepted socket, not sent by the client, so it cannot be forged by a
    script or another container that simply sets both headers itself.
    """
    return peer in _LOOPBACK_PEERS


def origin_allowed(origin: str, host: str) -> bool:
    """True when `origin`'s host:port is exactly the app's own `host` header,
    and the origin's hostname is a loopback identity (or explicitly allowed).

    Compares the full authority, so neither a different port on the same host
    nor a hostname that merely starts with ours ("localhost:5627.evil.example")
    passes. An absent Origin is refused: every browser sends one on a WebSocket
    handshake, so its absence means the caller is not a browser. Origin and
    Host agreeing is not sufficient on its own: under DNS rebinding an
    attacker controls both, so the hostname is also checked against
    `allowed_origin_hostnames()`. (`peer_allowed` is what makes it safe to
    widen that allowlist at all.)
    """
    if not origin or not host:
        return False
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    if parsed.netloc.casefold() != host.casefold():
        return False
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if hostname not in allowed_origin_hostnames():
        return False
    return True


def novnc_url() -> str:
    """The in-network websockify endpoint the browser container serves."""
    port = os.environ.get("BROWSER_NOVNC_PORT", "7900")
    return f"ws://browser:{port}/websockify"


async def relay(websocket: WebSocket) -> None:
    """Accept a viewer socket and pump bytes both ways to the browser container."""
    peer = websocket.client.host if websocket.client else ""
    if not peer_allowed(peer):
        # 1008 = policy violation. Closed before accept, so nothing is relayed.
        await websocket.close(code=1008)
        return

    origin = websocket.headers.get("origin", "")
    host = websocket.headers.get("host", "")
    if not origin_allowed(origin, host):
        # 1008 = policy violation. Closed before accept, so nothing is relayed.
        await websocket.close(code=1008)
        return

    await websocket.accept(subprotocol="binary")
    try:
        async with websockets.connect(novnc_url(), subprotocols=["binary"]) as upstream:

            async def viewer_to_browser() -> None:
                try:
                    while True:
                        # receive(), not receive_bytes(): a stray text frame
                        # has no "bytes" key and receive_bytes() would raise
                        # KeyError on it instead of just dropping it.
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        data = message.get("bytes")
                        if data is not None:
                            await upstream.send(data)
                except (WebSocketDisconnect, RuntimeError):
                    return

            async def browser_to_viewer() -> None:
                try:
                    async for message in upstream:
                        await websocket.send_bytes(message)
                except websockets.ConnectionClosed:
                    return

            # First side to finish (viewer or browser hangs up) wins; the
            # other is cancelled rather than left running against a dead peer.
            tasks = [
                asyncio.create_task(viewer_to_browser()),
                asyncio.create_task(browser_to_viewer()),
            ]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except (OSError, websockets.WebSocketException):
        # The browser container is unreachable, or didn't complete a valid
        # WebSocket handshake (wrong service on the port, no "binary"
        # subprotocol offered, etc). 1011 = internal error; the page shows
        # its "browser unavailable" state rather than a blank canvas.
        if websocket.application_state == WebSocketState.CONNECTED:
            try:
                await websocket.close(code=1011)
            except (RuntimeError, WebSocketDisconnect):
                # The viewer already disconnected; nothing left to close.
                pass
