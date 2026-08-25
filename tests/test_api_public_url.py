"""api.config.public_url() across every combination of PUBLIC_PORT/PORT.

PUBLIC_PORT is the host-side port docker-compose publishes, used purely to
log a reachable URL at startup; PORT is the port the process actually binds
inside the container. public_url() must prefer a numeric PUBLIC_PORT and
otherwise fall back to port().
"""

from __future__ import annotations

from api.config import public_url


def test_public_port_wins_over_bound_port(monkeypatch):
    """A set, numeric PUBLIC_PORT is used even when PORT differs."""
    monkeypatch.setenv("PUBLIC_PORT", "8123")
    monkeypatch.setenv("PORT", "8080")
    assert public_url() == "http://localhost:8123"


def test_falls_back_to_bound_port_when_public_port_unset(monkeypatch):
    """Local dev runs with no PUBLIC_PORT report the port actually bound."""
    monkeypatch.delenv("PUBLIC_PORT", raising=False)
    monkeypatch.setenv("PORT", "8080")
    assert public_url() == "http://localhost:8080"


def test_falls_back_to_ports_own_default_when_neither_is_set(monkeypatch):
    """With no env at all, this matches port()'s own 8080 default."""
    monkeypatch.delenv("PUBLIC_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    assert public_url() == "http://localhost:8080"


def test_non_numeric_public_port_falls_back_to_port(monkeypatch):
    """A malformed PUBLIC_PORT (empty or non-digit) never raises."""
    monkeypatch.setenv("PUBLIC_PORT", "abc")
    monkeypatch.setenv("PORT", "8080")
    assert public_url() == "http://localhost:8080"

    monkeypatch.setenv("PUBLIC_PORT", "")
    assert public_url() == "http://localhost:8080"
