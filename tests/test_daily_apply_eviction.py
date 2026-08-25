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


def test_the_wait_loop_re_issues_the_eviction():
    """A single evict can be dropped: the session server refuses one issued
    during open()'s reservation window, and daily-apply.sh checks only the HTTP
    status, never the body. Re-issuing on every pass of the wait loop is what
    makes a dropped eviction self-heal instead of costing the whole run."""
    body = SCRIPT.split("wait_for_session_release() {", 1)[1].split("\n    }", 1)[0]
    assert "/session/evict" in body


def test_a_failure_to_re_issue_the_eviction_is_not_ignored():
    """The re-issued evict fails closed the same way the first one does."""
    body = SCRIPT.split("wait_for_session_release() {", 1)[1].split("\n    }", 1)[0]
    assert "session_request POST /session/evict >/dev/null || return 1" in body
