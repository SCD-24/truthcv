"""Semi-auto queues a posting the agent would otherwise apply to.

Enforced in the store rather than the prompt, for the same reason a `deferred`
verdict is: record_screening(**fields) reaches create() directly, so a model
that ignores its instructions still cannot put a posting past the operator.
"""

from __future__ import annotations

import agentconfig.store as config_store
import screening.store as store


def _set_mode(mode: str) -> None:
    config_store.save(config_store.AgentConfig(mode=mode))


def test_passed_is_queued_in_semi(data_dir):
    _set_mode("semi")
    s = store.create({"company": "Contoso Labs", "verdict": "passed"})
    assert s.approval == "pending"


def test_passed_is_not_queued_in_full(data_dir):
    _set_mode("full")
    s = store.create({"company": "Contoso Labs", "verdict": "passed"})
    assert s.approval == ""


def test_deferred_is_queued_in_both_modes(data_dir):
    _set_mode("full")
    assert store.create({"company": "A", "verdict": "deferred"}).approval == "pending"
    _set_mode("semi")
    assert store.create({"company": "B", "verdict": "deferred"}).approval == "pending"


def test_rejected_is_never_queued(data_dir):
    _set_mode("semi")
    assert store.create({"company": "A", "verdict": "rejected"}).approval == ""


def test_posting_text_and_posted_date_round_trip(data_dir):
    s = store.create(
        {
            "company": "Contoso Labs",
            "verdict": "passed",
            "posting_text": "Staff AI Engineer. Germany (Remote). EUR 100k-130k.",
            "posted_date": "2026-08-20",
        }
    )
    loaded = store.get(s.id)
    assert loaded.posting_text.startswith("Staff AI Engineer")
    assert loaded.posted_date == "2026-08-20"


def test_approval_still_cannot_be_set_by_a_caller(data_dir):
    """The invariant the whole approval boundary rests on."""
    s = store.create({"company": "A", "verdict": "rejected", "approval": "approved"})
    assert s.approval == ""
