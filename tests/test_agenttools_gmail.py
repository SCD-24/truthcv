"""check_gmail_responses agent tool: the same Jev-opt-in gate as the routes,
then a run_sync call summarized as skipped/processed/applied/pending.

Patterned on tests/test_agent_mcp.py's tool-level tests. gmailsync.service and
gmailsync.store are always mocked — no live network call is made.
"""

from __future__ import annotations

import pytest

import secretstore
from agenttools.tools_gmail import check_gmail_responses
from gmailsync.model import GmailSuggestion

FERNET_KEY = "h2oN5GQVeWVhciVjWNImtAmWFyPGlrWvDCq8vXuqfmo="


@pytest.fixture(autouse=True)
def encryption(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    # An exported JEV_API_KEY would otherwise fill secretstore.get_connection's
    # apiKey from the environment, opening the gate even for the gate-closed
    # tests below and letting them hit the real network.
    monkeypatch.delenv("JEV_API_KEY", raising=False)


def _open_gate() -> None:
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForEmailTracking": True})


def test_gate_closed_no_connection_raises(data_dir):
    with pytest.raises(ValueError):
        check_gmail_responses()


def test_gate_closed_key_without_toggle_raises(data_dir):
    secretstore.set_connection("jev", {"apiKey": "jev_secret"})
    with pytest.raises(ValueError):
        check_gmail_responses()


def test_gate_closed_toggle_without_key_raises(data_dir):
    secretstore.set_connection("jev", {"useForEmailTracking": True})
    with pytest.raises(ValueError):
        check_gmail_responses()


def test_gate_open_runs_sync_and_returns_summary(data_dir, monkeypatch):
    _open_gate()
    monkeypatch.setattr(
        "gmailsync.service.run_sync",
        lambda: {"skipped": False, "last_synced_at": 100.0, "processed": 3, "suggestions": 2},
    )
    # load_suggestions is called twice by check_gmail_responses (before and
    # after run_sync); return the pre-sync snapshot first, then the post-sync
    # one, so "applied" reflects only THIS sync's newly-applied transition.
    before = [GmailSuggestion(id="m1", state="applied")]
    after = [
        GmailSuggestion(id="m1", state="applied"),
        GmailSuggestion(id="m2", state="applied"),
        GmailSuggestion(id="m3", state="pending"),
        GmailSuggestion(id="m4", state="pending"),
    ]
    snapshots = iter([before, after])
    monkeypatch.setattr("gmailsync.store.load_suggestions", lambda: next(snapshots))
    result = check_gmail_responses()
    assert result == {"skipped": False, "processed": 3, "applied": 1, "pending": 2}


def test_gate_open_skipped_sync_passes_through(data_dir, monkeypatch):
    """A throttled sync's skipped=True must be reported unchanged, not discarded."""
    _open_gate()
    monkeypatch.setattr(
        "gmailsync.service.run_sync",
        lambda: {"skipped": True, "last_synced_at": 100.0, "processed": 0, "suggestions": 2},
    )
    suggestions = [
        GmailSuggestion(id="m1", state="applied"),
        GmailSuggestion(id="m2", state="pending"),
    ]
    monkeypatch.setattr("gmailsync.store.load_suggestions", lambda: suggestions)
    result = check_gmail_responses()
    assert result == {"skipped": True, "processed": 0, "applied": 0, "pending": 1}
