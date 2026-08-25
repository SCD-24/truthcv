"""Host port assignment for the compose stack.

Bootstrap does not probe for a free port, and cannot: it runs inside a
container, where binding a socket tests the container's network namespace
rather than the host's, and `--network host` does not exist on Docker Desktop
for macOS or Windows. A probe from in there would report ports free that the
host has bound.

Docker's own bind attempt is the authoritative signal. The launcher runs
compose, and calls `bump` only when compose reports a port conflict — so a
port already recorded in .env is never moved speculatively.
"""

from __future__ import annotations

DEFAULTS: dict[str, int] = {"APP_PORT": 5627, "NOVNC_HOST_PORT": 5628}

MAX_PORT = 65535


def default_for(key: str) -> int:
    """The shipped default for a host port variable."""
    return DEFAULTS[key]


def bump(current: int, reserved: set[int]) -> int:
    """The next candidate above `current`, skipping `reserved`.

    `reserved` carries the ports already assigned to the other host variables,
    so an app port advancing past 5627 cannot land on the noVNC default.
    """
    candidate = current + 1
    while candidate in reserved:
        candidate += 1
    if candidate > MAX_PORT:
        raise ValueError(f"No port available above {current}.")
    return candidate
