"""GET /api/runs and GET /api/runs/{run_id}, and /api/agent/status tolerating
a supervisor payload without the run id keys."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from runs import store


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def test_list_runs_newest_first_and_honours_limit(client):
    for i in range(3):
        store.start(f"run-{i}", trigger="scheduled", apply_cap=0)
        all_runs = store.load_all()
        for rec in all_runs:
            if rec.id == f"run-{i}":
                rec.started_at = f"2024-01-0{i + 1}T00:00:00+00:00"
        store._write_all(all_runs)

    r = client.get("/api/runs")
    assert r.status_code == 200
    ids = [run["id"] for run in r.json()["runs"]]
    assert ids == ["run-2", "run-1", "run-0"]

    r = client.get("/api/runs?limit=2")
    assert len(r.json()["runs"]) == 2


def test_get_run_404_on_unknown_id(client):
    r = client.get("/api/runs/does-not-exist")
    assert r.status_code == 404


def test_run_record_full_field_set_survives_the_wire(client):
    """postings_seen and over_cap_writes are agent-reported, stored, and survive
    store.bump verbatim; the four coverage counters are DERIVED on read from the
    run's real screening and application records, not from the stored record."""
    from screening import store as screening_store
    from applications import store as applications_store

    store.start("full-run", trigger="scheduled", apply_cap=7)
    store.bump("full-run", postings_seen=4, over_cap_writes=1)
    # Three screenings linked to this run: a plain rejection, a deferred one
    # (which queues for approval), and one the agent could not read at all —
    # a screening_blocker, which both counts as blocked and queues.
    screening_store.create(
        {
            "company": "Acme Corp",
            "role": "Senior Engineer",
            "url": "https://acme.example/jobs/1",
            "verdict": "rejected",
            "run_id": "full-run",
        }
    )
    screening_store.create(
        {
            "company": "Beta Ltd",
            "role": "Platform Engineer",
            "url": "https://beta.example/jobs/2",
            "verdict": "deferred",
            "run_id": "full-run",
        }
    )
    screening_store.create(
        {
            "company": "Gamma Inc",
            "role": "Backend Engineer",
            "url": "https://gamma.example/jobs/3",
            "screening_blocker": "unreadable",
            "run_id": "full-run",
        }
    )
    applications_store.create(
        {
            "company": "Acme Corp",
            "role": "Senior Engineer",
            "run_id": "full-run",
            "submitted": True,
        }
    )
    store.finish("full-run", status="failed", stopped_reason="browser died", note="context")

    r = client.get("/api/runs/full-run")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "full-run"
    assert body["status"] == "failed"
    assert body["trigger"] == "scheduled"
    assert body["applyCap"] == 7
    # Agent-reported counters: stored on the record and served verbatim.
    assert body["postingsSeen"] == 4
    assert body["overCapWrites"] == 1
    # Derived counters: counted from the three screenings and one application.
    assert body["screeningsRecorded"] == 3
    assert body["blockedCount"] == 1
    assert body["queuedForApproval"] == 2
    assert body["applicationsSubmitted"] == 1
    assert body["stoppedReason"] == "browser died"
    assert body["note"] == "context"
    assert body["startedAt"]
    assert body["finishedAt"]


def test_bumped_derived_counter_is_ignored_in_favour_of_the_records(client):
    """The key regression guard: a store.bump on a DERIVED counter must never
    reach the wire. The API recomputes screeningsRecorded from the records that
    exist, so a bumped 99 is discarded in favour of the single real screening."""
    from screening import store as screening_store

    store.start("full-run", trigger="scheduled", apply_cap=0)
    screening_store.create(
        {
            "company": "Acme Corp",
            "role": "Senior Engineer",
            "url": "https://acme.example/jobs/1",
            "verdict": "rejected",
            "run_id": "full-run",
        }
    )
    store.bump("full-run", screenings_recorded=99)

    r = client.get("/api/runs/full-run")
    assert r.status_code == 200
    assert r.json()["screeningsRecorded"] == 1


def test_legacy_run_with_no_linked_records_reports_zero_counters(client):
    """A run from before record linkage owns no screenings or applications, so
    its four derived counters read 0 and the request still succeeds — even when
    stale counters were bumped onto the stored record."""
    store.start("legacy-run", trigger="manual", apply_cap=0)
    store.bump("legacy-run", screenings_recorded=5, applications_submitted=3)

    r = client.get("/api/runs/legacy-run")
    assert r.status_code == 200
    body = r.json()
    assert body["screeningsRecorded"] == 0
    assert body["blockedCount"] == 0
    assert body["queuedForApproval"] == 0
    assert body["applicationsSubmitted"] == 0


def test_agent_status_tolerates_supervisor_payload_missing_run_ids(client, monkeypatch):
    import api.routes as routes

    def fake_forward(path, method="GET", **kwargs):
        return {
            "running": False,
            "cancelling": False,
            "lastStartedAt": None,
            "lastFinishedAt": None,
            "lastExitCode": None,
            "lastCancelled": False,
        }

    monkeypatch.setattr(routes, "_forward_to_supervisor", fake_forward)
    r = client.get("/api/agent/status")
    assert r.status_code == 200
    body = r.json()
    assert body["currentRunId"] is None
    assert body["lastRunId"] is None
