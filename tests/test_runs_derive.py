"""runs/derive.py: coverage counters derived from a run's own records."""

from __future__ import annotations

from applications.model import Application
from runs.derive import counters_by_run, derive_counters
from screening.model import Screening


def _screening(run_id: str, **kwargs) -> Screening:
    """Build a screening owned by ``run_id`` with the given overrides."""
    return Screening(id=kwargs.pop("id", "s"), run_id=run_id, **kwargs)


def _application(run_id: str, submitted: bool) -> Application:
    """Build an application owned by ``run_id``."""
    return Application(id="a", company="ACME", run_id=run_id, submitted=submitted)


def test_screenings_are_counted_only_for_their_own_run():
    screenings = [
        _screening("A", id="1"),
        _screening("A", id="2"),
        _screening("B", id="3"),
    ]
    assert derive_counters("A", screenings, [])["screenings_recorded"] == 2
    assert derive_counters("B", screenings, [])["screenings_recorded"] == 1


def test_blocked_counts_screening_blocker_not_apply_blocker():
    screenings = [
        _screening("A", id="1", screening_blocker="login_required"),
        _screening("A", id="2", apply_blocker="login_required"),
        _screening("A", id="3"),
    ]
    counters = derive_counters("A", screenings, [])
    assert counters["screenings_recorded"] == 3
    assert counters["blocked_count"] == 1


def test_queued_for_approval_counts_only_pending():
    screenings = [
        _screening("A", id="1", approval="pending"),
        _screening("A", id="2", approval="approved"),
        _screening("A", id="3", approval="rejected"),
        _screening("A", id="4", approval="applied"),
        _screening("A", id="5", approval=""),
    ]
    assert derive_counters("A", screenings, [])["queued_for_approval"] == 1


def test_applications_submitted_counts_only_submitted_for_that_run():
    applications = [
        _application("A", True),
        _application("A", False),
        _application("B", True),
    ]
    assert derive_counters("A", [], applications)["applications_submitted"] == 1
    assert derive_counters("B", [], applications)["applications_submitted"] == 1


def test_empty_run_id_returns_zeros_even_with_unlinked_records():
    screenings = [_screening("", id="1", approval="pending")]
    applications = [_application("", True)]
    assert derive_counters("", screenings, applications) == {
        "screenings_recorded": 0,
        "blocked_count": 0,
        "queued_for_approval": 0,
        "applications_submitted": 0,
    }


def test_counters_by_run_agrees_with_derive_counters():
    screenings = [
        _screening("A", id="1", approval="pending"),
        _screening("A", id="2", screening_blocker="unreadable"),
        _screening("B", id="3"),
        _screening("", id="4", approval="pending"),
    ]
    applications = [_application("A", True), _application("B", False)]
    indexed = counters_by_run(["A", "B", ""], screenings, applications)
    for run_id in ("A", "B", ""):
        assert indexed[run_id] == derive_counters(run_id, screenings, applications)
    assert indexed["A"] == {
        "screenings_recorded": 2,
        "blocked_count": 1,
        "queued_for_approval": 1,
        "applications_submitted": 1,
    }


def test_counters_by_run_traverses_each_input_list_once():
    class _CountingList(list):
        """A list that records how many times it was iterated."""

        passes = 0

        def __iter__(self):
            self.passes += 1
            return super().__iter__()

    screenings = _CountingList([_screening("A", id="1"), _screening("B", id="2")])
    applications = _CountingList([_application("A", True)])
    counters_by_run(["A", "B"], screenings, applications)
    assert screenings.passes == 1
    assert applications.passes == 1
