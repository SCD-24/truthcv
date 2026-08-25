"""Host port defaults and next-candidate selection.

There is no probing here, and that is deliberate: bootstrap runs inside a
container, where binding a socket tests the container's network namespace
rather than the host's. Docker's own bind attempt is the only authoritative
signal, so these functions just decide what to try next.
"""

from __future__ import annotations

import pytest

from launcher import ports


def test_defaults_are_5627_and_5628():
    assert ports.DEFAULTS == {"APP_PORT": 5627, "NOVNC_HOST_PORT": 5628}


def test_default_for_returns_the_configured_port():
    assert ports.default_for("APP_PORT") == 5627
    assert ports.default_for("NOVNC_HOST_PORT") == 5628


def test_bump_advances_by_one():
    assert ports.bump(5627, set()) == 5628


def test_bump_skips_reserved_ports():
    """An app port advancing past 5627 must not land on the noVNC default."""
    assert ports.bump(5627, {5628}) == 5629


def test_bump_skips_a_run_of_reserved_ports():
    assert ports.bump(5627, {5628, 5629, 5630}) == 5631


def test_bump_raises_past_the_maximum():
    with pytest.raises(ValueError):
        ports.bump(ports.MAX_PORT, set())
