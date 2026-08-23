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


def test_set_approved_unknown_company(data_dir):
    assert boards.set_approved("Nobody", True) is None


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
