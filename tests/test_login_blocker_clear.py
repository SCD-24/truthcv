"""Clearing login blockers for a host when the operator signs in."""

from __future__ import annotations

import pytest

from screening import store
from services.screenings import clear_login_blockers_for_host


def _blocked_approved(company: str, url: str, signin_url: str = "") -> str:
    """Create an approved screening with a login_required blocker."""
    s = store.create({"company": company, "role": "Dev", "verdict": "passed", "url": url})
    store.set_approval(s.id, "approved")
    store.record_apply_failure(
        s.id, "sign-in required", blocker="login_required", signin_url=signin_url
    )
    return s.id


def _blocked_pending(company: str, url: str, signin_url: str = "") -> str:
    """Create a pending screening with a login_required blocker."""
    s = store.create({"company": company, "role": "Dev", "verdict": "passed", "url": url})
    store.set_approval(s.id, "pending")
    store.record_apply_failure(
        s.id, "sign-in required", blocker="login_required", signin_url=signin_url
    )
    return s.id


def test_clears_matching_host_approved_items(data_dir):
    """Login blockers for matching host approved items are cleared."""
    sid = _blocked_approved(
        "Acme",
        "https://acme.wd3.myworkdayjobs.com/careers/job/1",
        "https://acme.wd3.myworkdayjobs.com/login",
    )
    count = clear_login_blockers_for_host("acme.wd3.myworkdayjobs.com")
    assert count == 1
    s = store.get(sid)
    assert s.apply_blocker == ""
    assert s.signin_url == ""
    assert s.apply_error == ""


def test_clears_matching_host_pending_items(data_dir):
    """Login blockers for matching host pending items are cleared."""
    sid = _blocked_pending(
        "Acme",
        "https://acme.wd3.myworkdayjobs.com/careers/job/1",
        "https://acme.wd3.myworkdayjobs.com/login",
    )
    count = clear_login_blockers_for_host("acme.wd3.myworkdayjobs.com")
    assert count == 1
    s = store.get(sid)
    assert s.apply_blocker == ""
    assert s.signin_url == ""


def test_clears_when_signin_url_matches(data_dir):
    """Clears items where signin_url has the matching host."""
    sid = _blocked_approved(
        "Acme",
        "https://acme.wd3.myworkdayjobs.com/careers/job/1",
        "https://acme.wd3.myworkdayjobs.com/login",
    )
    count = clear_login_blockers_for_host("acme.wd3.myworkdayjobs.com")
    assert count == 1
    assert store.get(sid).apply_blocker == ""


def test_clears_when_url_matches_and_no_signin_url(data_dir):
    """Clears items where url has the matching host when signin_url is absent."""
    sid = _blocked_approved(
        "Acme",
        "https://acme.wd3.myworkdayjobs.com/careers/job/1",
        signin_url="",
    )
    count = clear_login_blockers_for_host("acme.wd3.myworkdayjobs.com")
    assert count == 1
    assert store.get(sid).apply_blocker == ""


def test_leaves_different_host_untouched(data_dir):
    """Items at a different host are left untouched."""
    sid = _blocked_approved(
        "Acme",
        "https://acme.wd3.myworkdayjobs.com/careers/job/1",
        "https://acme.wd3.myworkdayjobs.com/login",
    )
    count = clear_login_blockers_for_host("other.example.com")
    assert count == 0
    s = store.get(sid)
    assert s.apply_blocker == "login_required"
    assert s.signin_url == "https://acme.wd3.myworkdayjobs.com/login"


def test_leaves_non_login_blockers_untouched(data_dir):
    """Items with other blocker types (cooldown, unreadable) are untouched."""
    s = store.create(
        {
            "company": "Acme",
            "role": "Dev",
            "verdict": "passed",
            "url": "https://acme.wd3.myworkdayjobs.com/careers/job/1",
        }
    )
    store.set_approval(s.id, "approved")
    store.record_apply_failure(s.id, "form error", blocker="unreadable")

    count = clear_login_blockers_for_host("acme.wd3.myworkdayjobs.com")
    assert count == 0
    s = store.get(s.id)
    assert s.apply_blocker == "unreadable"


def test_leaves_items_without_blocker_untouched(data_dir):
    """Items with no blocker set are untouched."""
    s = store.create(
        {
            "company": "Acme",
            "role": "Dev",
            "verdict": "passed",
            "url": "https://acme.wd3.myworkdayjobs.com/careers/job/1",
        }
    )
    store.set_approval(s.id, "approved")
    count = clear_login_blockers_for_host("acme.wd3.myworkdayjobs.com")
    assert count == 0


def test_leaves_rejected_items_untouched(data_dir):
    """Items with rejected approval are not cleared."""
    sid = _blocked_approved(
        "Acme",
        "https://acme.wd3.myworkdayjobs.com/careers/job/1",
        "https://acme.wd3.myworkdayjobs.com/login",
    )
    store.set_approval(sid, "rejected")
    count = clear_login_blockers_for_host("acme.wd3.myworkdayjobs.com")
    assert count == 0
    s = store.get(sid)
    assert s.apply_blocker == "login_required"


def test_leaves_applied_items_untouched(data_dir):
    """Items with applied approval are not cleared."""
    sid = _blocked_approved(
        "Acme",
        "https://acme.wd3.myworkdayjobs.com/careers/job/1",
        "https://acme.wd3.myworkdayjobs.com/login",
    )
    store.mark_applied(sid)
    count = clear_login_blockers_for_host("acme.wd3.myworkdayjobs.com")
    assert count == 0
    s = store.get(sid)
    assert s.apply_blocker == "login_required"


def test_host_comparison_is_case_insensitive(data_dir):
    """Host comparison is case-insensitive (netloc casefolded)."""
    sid = _blocked_approved(
        "Acme",
        "https://Acme.Example.Com/careers/job/1",
        "https://Acme.Example.Com/login",
    )
    count = clear_login_blockers_for_host("acme.example.com")
    assert count == 1
    assert store.get(sid).apply_blocker == ""


def test_clears_multiple_items_at_same_host(data_dir):
    """Clears all matching items when there are multiple at one host."""
    sid1 = _blocked_approved(
        "Acme",
        "https://acme.wd3.myworkdayjobs.com/careers/job/1",
        "https://acme.wd3.myworkdayjobs.com/login",
    )
    sid2 = _blocked_pending(
        "Acme",
        "https://acme.wd3.myworkdayjobs.com/careers/job/2",
        "https://acme.wd3.myworkdayjobs.com/login",
    )
    count = clear_login_blockers_for_host("acme.wd3.myworkdayjobs.com")
    assert count == 2
    assert store.get(sid1).apply_blocker == ""
    assert store.get(sid2).apply_blocker == ""


def test_preserves_apply_attempts(data_dir):
    """Clearing a blocker preserves apply_attempts."""
    s = store.create(
        {
            "company": "Acme",
            "role": "Dev",
            "verdict": "passed",
            "url": "https://acme.wd3.myworkdayjobs.com/careers/job/1",
        }
    )
    store.set_approval(s.id, "approved")
    # Simulate some apply attempts
    for _ in range(3):
        store.record_apply_failure(s.id, "error")
    # Now add the login blocker
    store.record_apply_failure(
        s.id,
        "sign-in required",
        blocker="login_required",
        signin_url="https://acme.wd3.myworkdayjobs.com/login",
    )
    attempts_before = store.get(s.id).apply_attempts

    clear_login_blockers_for_host("acme.wd3.myworkdayjobs.com")
    s_after = store.get(s.id)
    assert s_after.apply_attempts == attempts_before
    assert s_after.apply_blocker == ""
