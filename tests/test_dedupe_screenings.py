"""The one-off cleanup for records written before the store enforced the rule."""

from __future__ import annotations

import screening.store as screening_store
from scripts.dedupe_screenings import group_by_posting, main, plan


def _write(records: list[dict]) -> list:
    """Persist records directly, bypassing create_or_get's dedupe.

    The corpus this script exists to clean could not be produced through the
    store any more, so the fixture writes it the way the old code did.
    """
    from screening.model import Screening

    screening_store._write_all([Screening.from_dict(r) for r in records])
    return screening_store.load_all()


def _rec(rid: str, url: str, created: str, approval: str = "", verdict: str = "passed") -> dict:
    return {
        "id": rid,
        "company": "Grafana Labs",
        "role": "Senior Backend Engineer",
        "url": url,
        "created_at": created,
        "updated_at": created,
        "approval": approval,
        "verdict": verdict,
    }


URL = "https://job-boards.greenhouse.io/grafanalabs/jobs/6117334004"


def test_a_posting_with_one_record_is_left_alone():
    _write([_rec("a", URL, "2026-08-23T00:00:00+00:00")])
    assert plan(screening_store.load_all()) == []


def test_cosmetically_different_urls_are_one_group():
    records = _write(
        [
            _rec("a", URL, "2026-08-23T00:00:00+00:00"),
            _rec("b", URL + "/apply?utm_source=alert", "2026-08-24T00:00:00+00:00"),
        ]
    )
    assert len(group_by_posting(records)) == 1


def test_records_with_no_resolvable_url_are_never_grouped():
    records = _write(
        [
            _rec("a", "", "2026-08-23T00:00:00+00:00"),
            _rec("b", "", "2026-08-24T00:00:00+00:00"),
            _rec("c", "not a url", "2026-08-25T00:00:00+00:00"),
        ]
    )
    assert group_by_posting(records) == {}
    assert plan(records) == []


def test_the_decided_record_outranks_a_newer_undecided_one():
    """The reported symptom: keeping the newest would keep the pending copy
    and leave the posting sitting in the approval queue."""
    records = _write(
        [
            _rec("old", URL, "2026-08-23T00:00:00+00:00", approval="rejected"),
            _rec("new", URL, "2026-08-26T00:00:00+00:00", approval="pending"),
        ]
    )
    keeper, dupes = plan(records)[0]
    assert keeper.id == "old"
    assert [d.id for d in dupes] == ["new"]


def test_an_applied_record_outranks_everything():
    records = _write(
        [
            _rec("applied", URL, "2026-08-23T00:00:00+00:00", approval="applied"),
            _rec("later", URL, "2026-08-26T00:00:00+00:00", approval="approved"),
        ]
    )
    assert plan(records)[0][0].id == "applied"


def test_the_newest_wins_within_one_decision_level():
    records = _write(
        [
            _rec("old", URL, "2026-08-23T00:00:00+00:00", approval="rejected"),
            _rec("new", URL, "2026-08-26T00:00:00+00:00", approval="rejected"),
        ]
    )
    assert plan(records)[0][0].id == "new"


def test_a_dry_run_writes_nothing():
    _write(
        [
            _rec("a", URL, "2026-08-23T00:00:00+00:00", approval="rejected"),
            _rec("b", URL, "2026-08-26T00:00:00+00:00", approval="rejected"),
        ]
    )
    assert main([]) == 0
    assert len(screening_store.load_all()) == 2


def test_apply_leaves_exactly_one_record_per_posting():
    _write(
        [
            _rec("a", URL, "2026-08-23T00:00:00+00:00", approval="rejected"),
            _rec("b", URL, "2026-08-24T00:00:00+00:00", approval="rejected"),
            _rec("c", URL + "/apply", "2026-08-26T00:00:00+00:00", approval="pending"),
            _rec("other", "https://x.example.com/j/abc", "2026-08-26T00:00:00+00:00"),
        ]
    )
    assert main(["--apply"]) == 0
    survivors = screening_store.load_all()
    assert sorted(s.id for s in survivors) == ["b", "other"]


def test_apply_is_idempotent():
    _write(
        [
            _rec("a", URL, "2026-08-23T00:00:00+00:00", approval="rejected"),
            _rec("b", URL, "2026-08-26T00:00:00+00:00", approval="rejected"),
        ]
    )
    main(["--apply"])
    before = [s.id for s in screening_store.load_all()]
    main(["--apply"])
    assert [s.id for s in screening_store.load_all()] == before


def test_apply_removes_the_duplicates_cover_letter_drafts():
    """delete_many carries the orphaned draft with the record it belonged to."""
    from coverletter.store import CoverLetterDraft
    from coverletter import store as letter_store

    _write(
        [
            _rec("a", URL, "2026-08-23T00:00:00+00:00", approval="rejected"),
            _rec("b", URL, "2026-08-26T00:00:00+00:00", approval="rejected"),
        ]
    )
    letter_store.save("a", CoverLetterDraft(text="draft for the duplicate"))
    letter_store.save("b", CoverLetterDraft(text="draft for the keeper"))

    main(["--apply"])

    assert letter_store.load("a") is None
    assert letter_store.load("b") is not None
