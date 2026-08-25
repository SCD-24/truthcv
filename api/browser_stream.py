"""Relay the browser container's noVNC WebSocket through the app.

The `browser` service's noVNC port is not published: the operator reaches the
viewport through this route instead, so there is one address and one place to
guard rather than a second passwordless port on every interface.

That guard is three checks, all run before `websocket.accept()`:

- `peer_allowed` requires the TCP peer to be loopback, or — only when this
  process is actually running inside a container (`_running_in_container`) —
  the container's default gateway (see `_default_gateway`, that is the
  address the operator's own browser arrives as once Docker NATs a published
  port; a sibling container keeps its own address). On a bare host the same
  gateway lookup would just name the LAN router, so it is trusted only where
  it means "arrived from the host". Origin and Host are both set by the
  client, so a non-browser caller — including another container on the
  compose network, such as `agent`, which runs LLM-driven code over
  attacker-controlled job-posting text — can simply send whatever it wants
  for either. The peer address is the one signal it cannot forge.
- `origin_allowed` requires the Origin header to match Host and to be a
  loopback (or explicitly allowed) hostname, defending the browser-reachable
  path: WebSocket handshakes are exempt from the same-origin policy and the
  CORS middleware in `api/main.py` does not see them, so without this check
  any page the operator visits while a session is open could open this
  socket and drive a browser holding their live sessions.
- `session_is_open` requires the browser container's session server to report
  an attended session actually open. Without it the two header/peer checks
  above still admit anything already on host loopback at ANY time — including
  mid-run, when the browser is being driven by `@playwright/mcp` through the
  operator's live ATS and email sessions, with x11vnc running `-nopw` and not
  view-only. This is the clause that bounds the exposure window to "while the
  operator has deliberately opened a session". An unreachable or unreadable
  session server refuses, like every other precondition in this design.

Two ways to defeat the peer check that are worth naming here, not just in
review notes:

- Setting `FORWARDED_ALLOW_IPS=*` makes uvicorn's `ProxyHeadersMiddleware`
  rewrite `scope["client"]` from the client-supplied `X-Forwarded-For` header
  for ANY peer, turning the one unforgeable signal this module relies on into
  a forgeable one. Nothing in this repo sets it today; if that ever changes,
  this gate is defeated.
- Behind a reverse proxy, every request's peer is the proxy itself, so this
  check degrades to "always true" and Origin/Host become the only remaining
  defence. Do not deploy this behind a proxy that isn't also forwarding the
  real client address through a mechanism this module has been updated to
  trust.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import urllib.error
import urllib.request
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


def _default_gateway(path: str = "/proc/net/route") -> str:
    """The address host traffic appears as inside a container.

    Docker NATs a published port, so a request from the operator's own browser
    reaches this process with the bridge gateway as its source — never
    127.0.0.1. Sibling containers on the same network keep their own addresses,
    so the gateway is precisely "arrived from the host" and does not admit the
    agent or browser containers.

    `path` is overridable so this can be pinned against a fixture route table
    in tests, rather than only ever exercising whatever route the machine
    running the tests happens to have.
    """
    try:
        with open(path) as fh:
            for line in fh.readlines()[1:]:
                fields = line.split()
                if len(fields) > 2 and fields[1] == "00000000":
                    return str(ipaddress.IPv4Address(int(fields[2], 16).to_bytes(4, "little")))
    except (OSError, ValueError):
        pass
    return ""


# Resolved once at import: the default route cannot change during the
# process's life. Outside a container /proc/net/route may be absent or name a
# different route; "" from `_default_gateway` means "no extra peer allowed",
# never "allow everything" (see `allowed_peers`).
_DEFAULT_GATEWAY = _default_gateway()


def _running_in_container(marker: str = "/.dockerenv") -> bool:
    """True when this process is running inside a (Docker) container.

    The gateway is trusted ONLY inside a container, where it is how host
    traffic arrives through Docker's NAT. On a bare host the same lookup
    returns the LAN router, which has no business reaching this socket —
    running `api/main.py` directly binds `0.0.0.0`, and without this check
    the router's address would be silently admitted.

    `marker` is overridable so the decision is testable without depending on
    where the tests happen to run.
    """
    return os.path.exists(marker)


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


_logged_extra_peers = False


def allowed_peers() -> frozenset[str]:
    """Loopback plus, when running inside a container, the default gateway
    (see `_default_gateway` and `_running_in_container`), extended via
    BROWSER_STREAM_ALLOWED_PEERS (comma-separated) for a deployment this does
    not fit — e.g. Podman, containerd, or Kubernetes, where the gateway is not
    trusted and this is the escape hatch that lets the operator's own browser
    through instead. An unresolved gateway ("") is dropped rather than
    included, so a failure to resolve it never widens the allowlist — and
    outside a container the gateway is never trusted at all, since there it
    is just the LAN router.
    """
    global _logged_extra_peers
    extra = os.environ.get("BROWSER_STREAM_ALLOWED_PEERS", "")
    peers = {p.strip() for p in extra.split(",") if p.strip()}
    if peers and not _logged_extra_peers:
        # This is the one unforgeable signal in the module; widening it is
        # logged just as loudly as widening the (weaker) Origin allowlist.
        logger.warning(
            "BROWSER_STREAM_ALLOWED_PEERS widens the browser-stream peer allowlist: %s",
            sorted(peers),
        )
        _logged_extra_peers = True
    if _DEFAULT_GATEWAY and _running_in_container():
        peers.add(_DEFAULT_GATEWAY)
    return frozenset(_LOOPBACK_PEERS | peers)


def peer_allowed(peer: str) -> bool:
    """True when `peer` (the TCP client address) is loopback, the container's
    default gateway, or explicitly allowed.

    Unlike Origin and Host, the client address is filled in by uvicorn from
    the accepted socket, not sent by the client, so it cannot be forged by a
    script or another container that simply sets both headers itself — unless
    FORWARDED_ALLOW_IPS is set, see the module docstring.
    """
    if not peer:
        return False
    return peer in allowed_peers()


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
        # .port raises ValueError on a malformed authority such as
        # "localhost:5627.evil.example" — urlparse only splits at the first
        # colon, so .hostname would silently be "localhost" (in the allowlist)
        # with the bogus port never examined, unless this is checked.
        parsed.port
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


# One short request per handshake, not per frame: the check gates the accept
# and nothing after it. Kept well under the 10s `api/routes.py` allows itself,
# because a viewer socket waiting on it is a page that has not rendered yet.
_SESSION_QUERY_TIMEOUT = 3


def session_control_url() -> str:
    """The session server's own `GET /session`, same address `api/routes.py` uses."""
    port = os.environ.get("SESSION_SERVER_PORT", "8932")
    return f"http://browser:{port}/session"


def _fetch_session_open() -> bool:
    """True only when the session server positively reports an open session.

    Every other outcome — unreachable container, 403 on a missing or mismatched
    X-Agent-Token, unparseable body — returns False. A relay that cannot
    establish that a session is open must refuse: an error is not evidence the
    operator asked for this socket.
    """
    req = urllib.request.Request(
        session_control_url(),
        method="GET",
        headers={"X-Agent-Token": os.environ.get("AGENT_API_TOKEN", "")},
    )
    try:
        with urllib.request.urlopen(req, timeout=_SESSION_QUERY_TIMEOUT) as resp:
            return json.loads(resp.read()).get("open") is True
    except (OSError, ValueError) as exc:
        # urllib.error.HTTPError and URLError are both OSError subclasses.
        logger.warning("browser-stream session check failed, refusing relay: %s", exc)
        return False


async def session_is_open() -> bool:
    """`_fetch_session_open` off the event loop — urllib is blocking."""
    return await asyncio.to_thread(_fetch_session_open)


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

    if not await session_is_open():
        # No attended session — so there is nothing here the operator asked to
        # see, and relaying would hand out control of whatever the agent is
        # doing on the profile right now. Refused before accept, like the two
        # checks above, and refused when the session server cannot be reached.
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
