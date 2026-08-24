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
    s = store.create({"company": "Grafana", "role": "Staff", "verdict": "deferred"})
    assert s.approval == "pending"


def test_rejected_create_is_not_an_approval_item(data_dir):
    s = store.create({"company": "Pleo", "role": "Staff", "verdict": "rejected"})
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
    s = store.create({"company": "Grafana", "verdict": "deferred"})
    updated = store.set_approval(s.id, "approved")
    assert updated.approval == "approved"
    assert store.get(s.id).approval == "approved"


def test_set_approval_unknown_id_returns_none(data_dir):
    assert store.set_approval("nope", "approved") is None


def test_set_approval_rejects_bad_value(data_dir):
    s = store.create({"company": "Grafana", "verdict": "deferred"})
    with pytest.raises(ValueError):
        store.set_approval(s.id, "yes-please")


def test_record_apply_failure_increments_and_keeps_approval(data_dir):
    s = store.create({"company": "Grafana", "verdict": "deferred"})
    store.set_approval(s.id, "approved")
    store.record_apply_failure(s.id, "browser died")
    store.record_apply_failure(s.id, "form 404")
    reloaded = store.get(s.id)
    assert reloaded.apply_attempts == 2
    assert reloaded.apply_error == "form 404"
    assert reloaded.approval == "approved"


def test_mark_applied(data_dir):
    s = store.create({"company": "Grafana", "verdict": "deferred"})
    store.set_approval(s.id, "approved")
    assert store.mark_applied(s.id).approval == "applied"


# ---------------------------------------------------------------------------
# delete_many
# ---------------------------------------------------------------------------

class TestDeleteMany:
    """One write for a whole selection, rather than a loop over delete()."""

    def _three(self):
        from screening import store

        return [
            store.create({"company": f"Co{i}", "role": "Engineer", "url": f"https://e.com/{i}"})
            for i in range(3)
        ]

    def test_removes_every_named_id(self, data_dir):
        from screening import store

        a, b, c = self._three()
        removed = store.delete_many([a.id, c.id])
        assert sorted(removed) == sorted([a.id, c.id])
        assert [s.id for s in store.load_all()] == [b.id]

    def test_returns_only_ids_that_existed(self, data_dir):
        from screening import store

        a, _, _ = self._three()
        assert store.delete_many([a.id, "never-existed"]) == [a.id]

    def test_empty_list_is_a_no_op(self, data_dir):
        from screening import store

        self._three()
        assert store.delete_many([]) == []
        assert len(store.load_all()) == 3

    def test_all_unknown_ids_writes_nothing(self, data_dir):
        """No write at all when nothing matches — not a rewrite of the same list."""
        from screening import store

        self._three()
        before = store.screenings_path().read_text(encoding="utf-8")
        assert store.delete_many(["nope", "also-nope"]) == []
        assert store.screenings_path().read_text(encoding="utf-8") == before

    def test_duplicate_ids_delete_once(self, data_dir):
        from screening import store

        a, b, _ = self._three()
        assert store.delete_many([a.id, a.id]) == [a.id]
        assert b.id in [s.id for s in store.load_all()]

    def test_survivors_keep_their_fields(self, data_dir):
        """The rewrite must not flatten the records it keeps."""
        from screening import store

        a, b, _ = self._three()
        store.delete_many([a.id])
        kept = store.get(b.id)
        assert kept is not None
        assert kept.company == "Co1"
        assert kept.url == "https://e.com/1"
