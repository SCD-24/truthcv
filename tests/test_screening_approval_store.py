"""Approval state on the Screening record and the store functions that write it."""

from __future__ import annotations

import pytest

import screening.store as store
from screening.model import APPROVAL_VALUES, Screening


def test_approval_fields_default_to_empty():
    s = Screening()
    assert s.approval == ""
    assert s.apply_attempts == 0
    assert s.apply_error == ""


def test_approval_fields_are_not_editable():
    """EDITABLE is what the agent's record_screening can set. If approval is in
    it, the agent can approve its own applications."""
    assert "approval" not in Screening.EDITABLE
    assert "apply_attempts" not in Screening.EDITABLE
    assert "apply_error" not in Screening.EDITABLE


def test_approval_values():
    assert APPROVAL_VALUES == ("", "pending", "approved", "rejected", "applied")


def test_round_trip_preserves_approval():
    s = Screening(id="x", approval="approved", apply_attempts=2, apply_error="boom")
    assert Screening.from_dict(s.to_dict()) == s


def test_deferred_create_becomes_pending(data_dir):
    s = store.create({"company": "Contoso", "role": "Staff", "verdict": "deferred"})
    assert s.approval == "pending"


def test_rejected_create_is_not_an_approval_item(data_dir):
    s = store.create({"company": "Soylent", "role": "Staff", "verdict": "rejected"})
    assert s.approval == ""


def test_caller_cannot_set_approval_through_create(data_dir):
    """The agent's record_screening(**fields) lands here."""
    s = store.create({"company": "X", "verdict": "rejected", "approval": "approved"})
    assert s.approval == ""


def test_caller_cannot_set_approval_through_update(data_dir):
    s = store.create({"company": "X", "verdict": "deferred"})
    store.update(s.id, {"approval": "approved", "company": "Y"})
    reloaded = store.get(s.id)
    assert reloaded.approval == "pending"
    assert reloaded.company == "Y"


def test_set_approval(data_dir):
    s = store.create({"company": "Contoso", "verdict": "deferred"})
    updated = store.set_approval(s.id, "approved")
    assert updated.approval == "approved"
    assert store.get(s.id).approval == "approved"


def test_set_approval_unknown_id_returns_none(data_dir):
    assert store.set_approval("nope", "approved") is None


def test_set_approval_rejects_bad_value(data_dir):
    s = store.create({"company": "Contoso", "verdict": "deferred"})
    with pytest.raises(ValueError):
        store.set_approval(s.id, "yes-please")


def test_record_apply_failure_increments_and_keeps_approval(data_dir):
    s = store.create({"company": "Contoso", "verdict": "deferred"})
    store.set_approval(s.id, "approved")
    store.record_apply_failure(s.id, "browser died")
    store.record_apply_failure(s.id, "form 404")
    reloaded = store.get(s.id)
    assert reloaded.apply_attempts == 2
    assert reloaded.apply_error == "form 404"
    assert reloaded.approval == "approved"


def test_clear_apply_failure_empties_error_fields(data_dir):
    s = store.create({"company": "Contoso", "verdict": "deferred"})
    store.set_approval(s.id, "approved")
    store.record_apply_failure(
        s.id, "outside allowed roots", blocker="login_required", signin_url="https://x/signin"
    )
    updated = store.clear_apply_failure(s.id)
    assert updated.apply_error == ""
    assert updated.apply_blocker == ""
    assert updated.signin_url == ""
    # Approval and the attempt count are history, not part of what a cleared
    # error touches.
    assert updated.approval == "approved"
    assert updated.apply_attempts == 1
    reloaded = store.get(s.id)
    assert reloaded.apply_error == ""
    assert reloaded.apply_attempts == 1


def test_clear_apply_failure_unknown_id_returns_none(data_dir):
    assert store.clear_apply_failure("nope") is None


def test_mark_applied(data_dir):
    s = store.create({"company": "Contoso", "verdict": "deferred"})
    store.set_approval(s.id, "approved")
    assert store.mark_applied(s.id).approval == "applied"
