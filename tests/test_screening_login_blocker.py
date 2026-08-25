"""Screening records carry a structured login-wall blocker, not just free text."""

from __future__ import annotations

from screening import store
from screening.model import Screening


def test_new_screening_defaults_to_no_blocker(data_dir):
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed"})
    assert s.apply_blocker == ""
    assert s.signin_url == ""


def test_record_apply_failure_stores_blocker_and_url(data_dir):
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed"})
    updated = store.record_apply_failure(
        s.id,
        "sign-in required",
        blocker="login_required",
        signin_url="https://acme.wd3.myworkdayjobs.com/login",
    )
    assert updated is not None
    assert updated.apply_blocker == "login_required"
    assert updated.signin_url == "https://acme.wd3.myworkdayjobs.com/login"
    assert updated.apply_attempts == 1
    assert updated.apply_error == "sign-in required"


def test_record_apply_failure_without_blocker_leaves_fields_empty(data_dir):
    """The existing two-argument call must keep working unchanged."""
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed"})
    updated = store.record_apply_failure(s.id, "form timed out")
    assert updated is not None
    assert updated.apply_blocker == ""
    assert updated.signin_url == ""


def test_blocker_fields_are_not_editable_by_the_agent():
    """record_screening(**fields) reaches store.create(); these must not be settable there."""
    assert "apply_blocker" not in Screening.EDITABLE
    assert "signin_url" not in Screening.EDITABLE


def test_records_persisted_before_these_fields_existed_still_load():
    """from_dict filters to known fields, so an old record loads with defaults."""
    old = {"id": "abc123", "company": "Acme", "role": "Dev", "verdict": "passed"}
    s = Screening.from_dict(old)
    assert s.apply_blocker == ""
    assert s.signin_url == ""
