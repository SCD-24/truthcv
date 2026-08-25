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
    store.start("full-run", trigger="scheduled", apply_cap=7)
    store.bump(
        "full-run",
        postings_seen=4,
        screenings_recorded=3,
        blocked_count=1,
        applications_submitted=2,
        over_cap_writes=1,
    )
    store.finish("full-run", status="failed", stopped_reason="browser died", note="context")

    r = client.get("/api/runs/full-run")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "full-run"
    assert body["status"] == "failed"
    assert body["trigger"] == "scheduled"
    assert body["applyCap"] == 7
    assert body["postingsSeen"] == 4
    assert body["screeningsRecorded"] == 3
    assert body["blockedCount"] == 1
    assert body["applicationsSubmitted"] == 2
    assert body["overCapWrites"] == 1
    assert body["stoppedReason"] == "browser died"
    assert body["note"] == "context"
    assert body["startedAt"]
    assert body["finishedAt"]


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
