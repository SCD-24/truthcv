"""API tests for /api/jobs: accept, poll, and the two registered kinds.

The underlying gmail-sync/feed-refresh functions are monkeypatched so these
tests never touch the network; polling to completion uses a
threading.Event the fake sets, not a sleep loop.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

import api.job_routes as job_routes
from api.main import app

_POLL_TIMEOUT_S = 5.0
_POLL_ROUNDS = 200


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def _poll_until_done(client: TestClient, job_id: str) -> dict:
    """Poll GET /api/jobs/{id} until it leaves pending/running, or fail."""
    for _ in range(_POLL_ROUNDS):
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "failed"):
            return body
    pytest.fail(f"job {job_id} never finished polling")


def test_post_unknown_kind_returns_404(client):
    resp = client.post("/api/jobs/not-a-real-kind")
    assert resp.status_code == 404


def test_get_unknown_job_id_returns_404(client):
    resp = client.get("/api/jobs/not-a-real-id")
    assert resp.status_code == 404


def test_feed_refresh_job_runs_to_done(client, monkeypatch):
    started = threading.Event()

    def fake_run_feed_refresh():
        started.set()
        return {"postings": [{"url": "https://example.com/1"}], "error": ""}

    monkeypatch.setitem(job_routes._JOB_KINDS, "feed-refresh", (None, fake_run_feed_refresh))

    resp = client.post("/api/jobs/feed-refresh")
    assert resp.status_code == 202
    body = resp.json()
    assert body["kind"] == "feed-refresh"
    # The fake runs almost instantly, so status may already be "done" by the
    # time this response is built; only "failed" would signal a real bug.
    assert body["status"] != "failed"
    job_id = body["id"]

    assert started.wait(_POLL_TIMEOUT_S)
    final = _poll_until_done(client, job_id)
    assert final["status"] == "done"
    assert final["result"] == {"postings": [{"url": "https://example.com/1"}], "error": ""}


def test_gmail_sync_job_runs_to_done_and_is_listed(client, monkeypatch):
    started = threading.Event()

    def fake_run_gmail_sync():
        started.set()
        return {"skipped": False, "processed": 3}

    monkeypatch.setitem(
        job_routes._JOB_KINDS, "gmail-sync", (lambda: None, fake_run_gmail_sync)
    )

    resp = client.post("/api/jobs/gmail-sync")
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    assert started.wait(_POLL_TIMEOUT_S)
    final = _poll_until_done(client, job_id)
    assert final["status"] == "done"
    assert final["result"] == {"skipped": False, "processed": 3}

    listed_ids = {j["id"] for j in client.get("/api/jobs").json()}
    assert job_id in listed_ids


def test_gmail_sync_job_is_gated_like_the_existing_sync_route(client):
    # No Jev key / opt-in saved, so the real guard should 403 the accept
    # itself rather than queueing a job that would fail asynchronously.
    resp = client.post("/api/jobs/gmail-sync")
    assert resp.status_code == 403
