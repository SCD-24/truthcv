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


def _dated_runs(count: int) -> None:
    """Record `count` runs with distinct, ascending started_at values."""
    for i in range(count):
        store.start(f"run-{i}", trigger="scheduled", apply_cap=0)
    all_runs = store.load_all()
    by_id = {r.id: r for r in all_runs}
    for i in range(count):
        by_id[f"run-{i}"].started_at = f"2024-01-{i + 1:02d}T00:00:00+00:00"
    store._write_all(all_runs)


def test_the_response_carries_the_total_across_all_pages(client):
    """A page cannot report how many pages exist, so the client cannot build
    pagination controls without this."""
    _dated_runs(12)
    body = client.get("/api/runs?limit=5").json()
    assert len(body["runs"]) == 5
    assert body["total"] == 12
    assert body["limit"] == 5
    assert body["offset"] == 0


def test_offset_returns_the_next_page_newest_first(client):
    _dated_runs(12)
    first = [r["id"] for r in client.get("/api/runs?limit=5&offset=0").json()["runs"]]
    second = [r["id"] for r in client.get("/api/runs?limit=5&offset=5").json()["runs"]]
    assert first == ["run-11", "run-10", "run-9", "run-8", "run-7"]
    assert second == ["run-6", "run-5", "run-4", "run-3", "run-2"]


def test_offset_past_the_end_is_an_empty_page_with_the_real_total(client):
    """The total is what tells the client it overshot; a 404 or an error here
    would turn a stale page number into a broken section."""
    _dated_runs(3)
    body = client.get("/api/runs?limit=5&offset=99").json()
    assert body["runs"] == []
    assert body["total"] == 3


def test_a_negative_offset_is_clamped_to_the_first_page(client):
    """A client that paged past the start gets the first page, not an error and
    not an empty one. Guarded in the route AND in the store's slice, because a
    negative index into a Python list reads from the END — which would serve
    the OLDEST runs to a caller that asked for the newest."""
    _dated_runs(12)
    body = client.get("/api/runs?limit=5&offset=-5").json()
    assert [r["id"] for r in body["runs"]] == ["run-11", "run-10", "run-9", "run-8", "run-7"]
    assert body["offset"] == 0


def test_omitting_offset_keeps_the_old_default_behaviour(client):
    _dated_runs(3)
    body = client.get("/api/runs").json()
    assert [r["id"] for r in body["runs"]] == ["run-2", "run-1", "run-0"]
    assert body["offset"] == 0


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


# --- host-side run accounting -----------------------------------------------
# POST /api/agent/runs/{id}/start and .../finish exist so a run that dies before
# the model's first turn still appears in Recent runs. Before them the only way
# a record came into being was the model calling the start_run MCP tool, so a
# provider error, an aborted precondition and a run that was never triggered all
# looked identical: nothing at all.


@pytest.fixture()
def agent_token(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "shared-secret")
    return {"X-Agent-Token": "shared-secret"}


def test_start_then_finish_records_a_run_that_never_reached_the_model(client, agent_token):
    r = client.post("/api/agent/runs/dead-on-arrival/start", json={"trigger": "manual"}, headers=agent_token)
    assert r.status_code == 200
    assert r.json() == {"recorded": True}

    listed = client.get("/api/runs").json()["runs"]
    assert [run["id"] for run in listed] == ["dead-on-arrival"]
    assert listed[0]["status"] == "running"
    assert listed[0]["trigger"] == "manual"

    r = client.post(
        "/api/agent/runs/dead-on-arrival/finish",
        json={"status": "failed", "stoppedReason": "the LLM provider rejected every attempt"},
        headers=agent_token,
    )
    assert r.json() == {"recorded": True}

    run = client.get("/api/runs/dead-on-arrival").json()
    assert run["status"] == "failed"
    assert run["stoppedReason"] == "the LLM provider rejected every attempt"


def test_finish_does_not_overwrite_the_agents_own_stopped_reason(client, agent_token):
    client.post("/api/agent/runs/r1/start", json={"trigger": "scheduled"}, headers=agent_token)
    store.finish("r1", status="completed", stopped_reason="apply cap reached")

    r = client.post(
        "/api/agent/runs/r1/finish",
        json={"status": "failed", "stoppedReason": "the run exited with code 3"},
        headers=agent_token,
    )
    assert r.json() == {"recorded": False}

    run = client.get("/api/runs/r1").json()
    assert run["status"] == "completed"
    assert run["stoppedReason"] == "apply cap reached"


def test_discovery_coverage_written_via_the_tool_survives_the_wire(client):
    """record_discovery_coverage entries land in the stored record and are
    served back as camelCase discoveryCoverage entries on GET /api/runs."""
    from agenttools import tools_runs

    store.start("cov-run", trigger="scheduled", apply_cap=0)
    result = tools_runs.record_discovery_coverage(
        run_id="cov-run",
        channel="feed",
        board="LinkedIn",
        status="searched",
        postings_found=5,
        reason="",
    )
    assert result["recorded"] is True

    run = client.get("/api/runs/cov-run").json()
    assert run["discoveryCoverage"] == [
        {
            "channel": "feed",
            "board": "LinkedIn",
            "status": "searched",
            "postingsFound": 5,
            "reason": "",
        }
    ]


def test_the_model_start_run_joins_the_host_created_record(client, agent_token):
    """runs.store.start is idempotent, so the agent's own start_run lands on the
    record the supervisor already created rather than resetting it — including
    the accurate trigger, which start_run could only ever guess."""
    from agenttools import tools_runs

    client.post("/api/agent/runs/r2/start", json={"trigger": "manual", "applyCap": 4}, headers=agent_token)
    joined = tools_runs.start_run(run_id="r2", trigger="scheduled", apply_cap=999)

    assert joined["recorded"] is True
    assert joined["trigger"] == "manual"
    assert joined["apply_cap"] == 4


def test_accounting_routes_are_404_without_the_agent_token(client, agent_token):
    """404 rather than 403, matching /api/agent/llm-credentials: the response
    carries no hint that the route exists. These routes write to the ledger the
    operator reads, so they are deliberately not on the unauthenticated /mcp
    tool surface."""
    assert client.post("/api/agent/runs/x/start", json={}).status_code == 404
    assert client.post("/api/agent/runs/x/finish", json={}).status_code == 404
    assert (
        client.post("/api/agent/runs/x/start", json={}, headers={"X-Agent-Token": "wrong"}).status_code
        == 404
    )
    assert client.get("/api/runs").json()["runs"] == []


def test_accounting_routes_are_404_when_no_token_is_configured(client, monkeypatch):
    """An unset shared secret must match nothing, not everything."""
    monkeypatch.delenv("AGENT_API_TOKEN", raising=False)
    assert client.post("/api/agent/runs/x/start", json={}, headers={"X-Agent-Token": ""}).status_code == 404


def test_finish_rejects_an_unknown_status_instead_of_storing_it(client, agent_token):
    client.post("/api/agent/runs/r3/start", json={}, headers=agent_token)
    r = client.post("/api/agent/runs/r3/finish", json={"status": "exploded"}, headers=agent_token)
    assert r.status_code == 422
    assert client.get("/api/runs/r3").json()["status"] == "running"


def test_limit_zero_means_every_retained_run(client):
    """`limit <= 0` means "no limit" — the contract runs.store documents and
    the old callers relied on. An external client can ask for it, so it is
    pinned at the HTTP layer and not only in the store."""
    _dated_runs(12)

    body = client.get("/api/runs?limit=0&offset=2").json()

    assert len(body["runs"]) == 10
    assert body["total"] == 12
    assert body["runs"][0]["id"] == "run-9"
