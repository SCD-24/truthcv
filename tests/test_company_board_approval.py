"""Company-level approval on the board record.

The agent re-records a company board every run. If record() rebuilds the entry
from its arguments, that silently un-approves the company — the defect this
guards.
"""

from __future__ import annotations

import companyboards.store as boards


def test_approved_defaults_false(data_dir):
    boards.record("Grafana Labs", "https://grafana.com/careers")
    assert boards.load()["grafana labs"].approved is False


def test_set_approved(data_dir):
    boards.record("Grafana Labs", "https://grafana.com/careers")
    assert boards.set_approved("Grafana Labs", True).approved is True
    assert boards.load()["grafana labs"].approved is True


def test_set_approved_creates_a_board_for_an_unresolved_company(data_dir):
    """Companies screened from a posting URL never had a board resolved; the
    operator must still be able to trust them."""
    entry = boards.set_approved("Nobody", True)
    assert entry.approved is True
    assert entry.company == "Nobody"
    assert entry.careers_url == ""
    assert entry.status == "unresolved"
    assert boards.load()["nobody"].approved is True


def test_prune_with_an_empty_watchlist_keeps_everything(data_dir):
    """An empty watchlist means "unconfigured", not "delete every board"."""
    boards.record("Grafana Labs", "https://grafana.com/careers")
    boards.prune([])
    assert "grafana labs" in boards.load()


def test_prune_keeps_approved_companies_off_the_watchlist(data_dir):
    boards.set_approved("Grafana Labs", True)
    boards.record("Other Co", "https://other.example/careers")
    boards.prune(["Other Co"])
    remaining = boards.load()
    assert remaining["grafana labs"].approved is True
    assert "other co" in remaining


def test_prune_still_drops_unapproved_companies_off_the_watchlist(data_dir):
    boards.record("Grafana Labs", "https://grafana.com/careers")
    boards.prune(["Other Co"])
    assert "grafana labs" not in boards.load()


def test_record_preserves_approval(data_dir):
    """The agent re-recording the board must not un-approve the company."""
    boards.record("Grafana Labs", "https://grafana.com/careers")
    boards.set_approved("Grafana Labs", True)
    boards.record("Grafana Labs", "https://grafana.com/jobs", ats="greenhouse")
    entry = boards.load()["grafana labs"]
    assert entry.approved is True
    assert entry.careers_url == "https://grafana.com/jobs"
    assert entry.ats == "greenhouse"


def test_approved_round_trips_through_disk(data_dir):
    boards.record("Grafana Labs", "https://grafana.com/careers")
    boards.set_approved("Grafana Labs", True)
    assert boards.load()["grafana labs"].approved is True
