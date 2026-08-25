"""The compose file must not publish a passwordless remote-control surface.

The noVNC viewport gives keyboard and mouse control of a browser holding the
operator's live ATS and email sessions, and x11vnc runs with -nopw. It is
reachable through the app's origin-checked relay instead.
"""

from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE = yaml.safe_load(Path("docker-compose.yml").read_text())


def test_the_novnc_port_is_not_published():
    browser = COMPOSE["services"]["browser"]
    for entry in browser.get("ports", []):
        assert "7900" not in str(entry), f"noVNC must not be published: {entry}"


def test_the_session_server_port_is_not_published():
    browser = COMPOSE["services"]["browser"]
    for entry in browser.get("ports", []):
        assert "8932" not in str(entry), f"session server must not be published: {entry}"


def test_the_app_is_bound_to_loopback():
    """The app has no authentication; it must not listen on every interface."""
    ports = COMPOSE["services"]["app"]["ports"]
    assert len(ports) == 1
    assert str(ports[0]).startswith("127.0.0.1:"), ports[0]
