"""Relay the browser container's noVNC WebSocket through the app.

The `browser` service's noVNC port is not published: the operator reaches the
viewport through this route instead, so there is one address and one place to
guard rather than a second passwordless port on every interface.

That guard is `origin_allowed`. WebSocket handshakes are exempt from the
same-origin policy and the CORS middleware in `api/main.py` does not see them,
so without an explicit check any page the operator visits while a session is
open could open this socket and drive a browser holding their live sessions.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from starlette.concurrency import run_until_first_complete


def origin_allowed(origin: str, host: str) -> bool:
    """True when `origin`'s host:port is exactly the app's own `host` header.

    Compares the full authority, so neither a different port on the same host
    nor a hostname that merely starts with ours ("localhost:5627.evil.example")
    passes. An absent Origin is refused: every browser sends one on a WebSocket
    handshake, so its absence means the caller is not a browser.
    """
    if not origin or not host:
        return False
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    return parsed.netloc.casefold() == host.casefold()


def novnc_url() -> str:
    """The in-network websockify endpoint the browser container serves."""
    port = os.environ.get("BROWSER_NOVNC_PORT", "7900")
    return f"ws://browser:{port}/websockify"


async def relay(websocket: WebSocket) -> None:
    """Accept a viewer socket and pump bytes both ways to the browser container."""
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
                        await upstream.send(await websocket.receive_bytes())
                except (WebSocketDisconnect, RuntimeError):
                    return

            async def browser_to_viewer() -> None:
                try:
                    async for message in upstream:
                        await websocket.send_bytes(message)
                except websockets.ConnectionClosed:
                    return

            await run_until_first_complete(
                (viewer_to_browser, {}),
                (browser_to_viewer, {}),
            )
    except OSError:
        # The browser container is unreachable. 1011 = internal error; the page
        # shows its "browser unavailable" state rather than a blank canvas.
        await websocket.close(code=1011)
