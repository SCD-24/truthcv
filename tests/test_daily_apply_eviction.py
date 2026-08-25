"""daily-apply.sh evicts an attended sign-in session before taking the browser."""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path("agent/daily-apply.sh").read_text()


def test_the_script_evicts_before_running():
    assert "/session/evict" in SCRIPT


def test_it_waits_for_the_session_to_close():
    """A grace period the run does not actually wait out is not a grace period."""
    assert "wait_for_session_release" in SCRIPT


def test_it_aborts_when_the_session_server_is_unreachable():
    """Fails closed, like every other precondition in this script."""
    assert "session server unreachable" in SCRIPT


def test_the_wait_is_bounded():
    """An unbounded wait turns a forgotten tab into a permanently skipped run."""
    assert "SESSION_EVICT_TIMEOUT" in SCRIPT
