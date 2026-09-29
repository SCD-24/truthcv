"""API-side contract for the bounded metadata-only supervisor diagnostics reader."""

import asyncio
import json
import socket
import urllib.error
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api import agent_diagnostics as diag
from runs import store as runs_store

RUN_ID = "run_test1"
AT = "2023-11-14T22:13:20.000Z"


def response(body):
    reply = MagicMock()
    reply.read.return_value = json.dumps(body).encode() if not isinstance(body, bytes) else body
    reply.__enter__.return_value = reply
    reply.__exit__.return_value = False
    return reply


def stub_open(monkeypatch, open_url):
    monkeypatch.setattr(diag.urllib.request, "build_opener",
                        lambda *handlers: SimpleNamespace(open=open_url))


def fixture_event(sequence=1, status="start"):
    # Mirrors createDiagnostics in agent/harness/diagnostics.ts.
    event = {"schema_version": 1, "run_id": RUN_ID, "sequence": sequence,
             "at": AT, "operation_id": "op_1", "phase": "model", "status": status,
             "active_operations": [{"operation_id": "op_1", "phase": "model", "started_at": AT}],
             "active_truncated": False, "truncated": False}
    if status != "start":
        event["duration_ms"] = 3
        event["active_operations"] = []
    return event


def fixture_page(running=True, current_run_id=RUN_ID, events=None, **overrides):
    events = [fixture_event()] if events is None else events
    return {"schema_version": 1, "run_id": RUN_ID, "running": running,
            "currentRunId": current_run_id, "observed_at": AT,
            "availability": "available", "reason": None, "events": events,
            "next_before_sequence": None, "truncated": False, "active_truncated": False,
            "last_activity_at": AT, "active_operations": fixture_event()["active_operations"] if running and current_run_id == RUN_ID else [],
            **overrides}


@pytest.fixture
def setup(data_dir, monkeypatch):
    runs_store.start(RUN_ID, trigger="scheduled")
    monkeypatch.setenv("AGENT_API_TOKEN", "private-agent-token")
    monkeypatch.setenv("AGENT_CONTROL_PORT", "9099")


def test_status_allowlist_get_only_and_fixed_host(setup, monkeypatch):
    captured = {}
    def open_url(req, timeout):
        captured.update(url=req.full_url, method=req.get_method(), timeout=timeout,
                        header=req.get_header("X-agent-token"))
        return response({"running": True, "currentRunId": RUN_ID, "lastRunId": RUN_ID,
                         "scheduleEnabled": True, "secret": "never echo"})
    stub_open(monkeypatch, open_url)
    result = asyncio.run(diag.get_agent_status())
    assert captured == {"url": "http://agent:9099/status", "method": "GET", "timeout": 5,
                        "header": "private-agent-token"}
    assert result["availability"] == "available" and result["running"] is True
    assert result["currentRunId"] == RUN_ID and "secret" not in result
    assert result["cancelling"] is False and result["lastCancelled"] is False
    assert result["observed_at"].endswith("Z")


@pytest.mark.parametrize("running,current,ownership", [
    (True, RUN_ID, "active"), (False, RUN_ID, "inactive"), (True, "other", "inactive"),
])
def test_events_ownership(setup, monkeypatch, running, current, ownership):
    stub_open(monkeypatch, lambda req, timeout: response(fixture_page(running, current)))
    result = asyncio.run(diag.get_run_events(RUN_ID))
    assert result["ownership"] == ownership
    assert result["active_truncated"] is False
    assert result["active_operations"] == (fixture_event()["active_operations"] if ownership == "active" else [])
    assert result["events"][0]["phase"] == "model"


def test_pagination_and_empty_old_page(setup, monkeypatch):
    urls = []
    def open_url(req, timeout):
        urls.append(req.full_url)
        return response(fixture_page(events=[], active_operations=[]))
    stub_open(monkeypatch, open_url)
    result = asyncio.run(diag.get_run_events(RUN_ID, limit=1, before_sequence=1))
    assert result["availability"] == "available" and result["events"] == []
    assert result["active_truncated"] is False
    assert urls == ["http://agent:9099/diagnostics/runs/run_test1/events?limit=1&before_sequence=1"]


@pytest.mark.parametrize("failure,reason,reachability", [
    (urllib.error.HTTPError("url", 403, "private", None, None), "token_mismatch", "reachable"),
    (urllib.error.HTTPError("url", 404, "old", None, None), "old_endpoint", "reachable"),
    (urllib.error.HTTPError("url", 500, "private", None, None), "upstream_error", "reachable"),
    (urllib.error.URLError("secret failure"), "unreachable", "unreachable"),
    (socket.timeout("secret timeout"), "timeout", "unreachable"),
    (urllib.error.URLError(socket.timeout("secret timeout")), "timeout", "unreachable"),
])
def test_network_failures_sanitized(setup, monkeypatch, failure, reason, reachability):
    def fail(*args, **kwargs):
        raise failure
    stub_open(monkeypatch, fail)
    result = asyncio.run(diag.get_run_events(RUN_ID))
    assert result["reason"] == reason and result["reachability"] == reachability
    assert result["ownership"] == "unknown" and result["active_operations"] == []
    assert "secret" not in json.dumps(result) and "private" not in json.dumps(result)


def test_missing_token_prevents_request(setup, monkeypatch):
    monkeypatch.delenv("AGENT_API_TOKEN")
    def fail(*args, **kwargs):
        pytest.fail("network request without token")
    stub_open(monkeypatch, fail)
    assert asyncio.run(diag.get_agent_status())["reason"] == "missing_token"
    assert asyncio.run(diag.get_run_events(RUN_ID))["reason"] == "missing_token"


@pytest.mark.parametrize("run_id,limit,before,reason", [
    ("../../secret", 50, None, "invalid_request"), (RUN_ID, 0, None, "invalid_request"),
    (RUN_ID, 201, None, "invalid_request"), (RUN_ID, True, None, "invalid_request"),
    (RUN_ID, 1, 0, "invalid_request"), ("missing", 50, None, "unknown_run"),
])
def test_rejects_unstored_or_unsafe_without_request(setup, monkeypatch, run_id, limit, before, reason):
    stub_open(monkeypatch, lambda *a, **k: pytest.fail("unexpected HTTP"))
    result = asyncio.run(diag.get_run_events(run_id, limit, before))
    assert result["reason"] == reason and result["ownership"] == "unknown"
    assert "../" not in json.dumps(result)


@pytest.mark.parametrize("payload,reason", [
    (fixture_page(availability="unavailable", reason="missing", events=[],
                  active_operations=[], last_activity_at=None), "absent_telemetry"),
    (fixture_page(availability="unavailable", reason="malformed", events=[],
                  active_operations=[], last_activity_at=None), "malformed_response"),
    (fixture_page(events=[{**fixture_event(), "content": "secret"}]), "malformed_response"),
    (fixture_page(events=[{**fixture_event(), "schema_version": 2}]), "malformed_response"),
    (fixture_page(events=[{**fixture_event(), "phase": ["model"]}]), "malformed_response"),
    (fixture_page(events=[fixture_event(2), fixture_event(1)]), "malformed_response"),
    (fixture_page(events=[fixture_event(1), fixture_event(1)]), "malformed_response"),
    (fixture_page(active_truncated="secret"), "malformed_response"),
    (fixture_page(active_truncated=True, running=False, active_operations=[]), "malformed_response"),
    (fixture_page(availability="unavailable", reason="missing", events=[], active_operations=[],
                  last_activity_at=None, active_truncated=True), "malformed_response"),
    (fixture_page(events=[{**fixture_event(), "tool_name": ["secret"]}]), "malformed_response"),
    (fixture_page(events=[{**fixture_event(), "operation_id": ["secret"]}]), "malformed_response"),
    (fixture_page(active_operations=[{"operation_id": "op_1", "phase": "tool", "started_at": AT,
                                      "tool_name": "secret args"}]), "malformed_response"),
    (fixture_page(events=[fixture_event()] * 201), "malformed_response"),
])
def test_schema_and_privacy_fail_closed(setup, monkeypatch, payload, reason):
    stub_open(monkeypatch, lambda req, timeout: response(payload))
    result = asyncio.run(diag.get_run_events(RUN_ID))
    assert result["reason"] == reason and result["events"] == []
    assert "secret" not in json.dumps(result)


def test_validated_unavailable_telemetry_keeps_supervisor_ownership(setup, monkeypatch):
    for running, current, ownership in [(True, RUN_ID, "active"), (False, RUN_ID, "inactive"),
                                         (True, "other", "inactive")]:
        page = fixture_page(running, current, availability="unavailable", reason="missing",
                            events=[], last_activity_at=None, active_operations=[])
        stub_open(monkeypatch, lambda req, timeout: response(page))
        result = asyncio.run(diag.get_run_events(RUN_ID))
        assert result["reason"] == "absent_telemetry"
        assert result["running"] is running and result["currentRunId"] == current
        assert result["ownership"] == ownership
        assert result["active_operations"] == [] and result["active_truncated"] is False


def test_producer_shaped_untrusted_live_telemetry_keeps_ownership(setup, monkeypatch):
    # Harness write+unlink failure leaves a valid old file, but the supervisor
    # child-bound lease invalidates it independently of the file contents.
    for running, current, ownership in [(True, RUN_ID, 'active'), (False, RUN_ID, 'inactive'),
                                         (True, 'other', 'inactive')]:
        page = fixture_page(running, current, availability='unavailable', reason='telemetry_unavailable',
                            events=[], active_operations=[], last_activity_at=None)
        stub_open(monkeypatch, lambda req, timeout: response(page))
        result = asyncio.run(diag.get_run_events(RUN_ID))
        assert result['reason'] == 'telemetry_unavailable'
        assert result['ownership'] == ownership
        assert result['running'] is running and result['currentRunId'] == current
        assert result['events'] == result['active_operations'] == []


def test_empty_page_with_truncated_latest_active_snapshot(setup, monkeypatch):
    # Snapshot fields describe the latest event, even when pagination returns no events.
    active = [{"operation_id": f"op_{i}", "phase": "model", "started_at": AT}
              for i in range(1, 129)]
    page = fixture_page(events=[], active_operations=active, active_truncated=True)
    stub_open(monkeypatch, lambda req, timeout: response(page))
    result = asyncio.run(diag.get_run_events(RUN_ID, limit=1, before_sequence=1))
    assert result["events"] == [] and result["active_operations"] == active
    assert result["active_truncated"] is True and result["ownership"] == "active"


def test_redirect_denied_by_urllib_before_any_credential_forwarding(setup, monkeypatch):
    monkeypatch.setattr(diag.urllib.request, "getproxies", lambda: {})
    requests = []

    def transport(self, req):
        requests.append((req.full_url, req.get_header("X-agent-token")))
        redirect = MagicMock()
        redirect.code = 302
        redirect.msg = "Found"
        redirect.info.return_value = {"Location": "http://attacker.invalid/collect"}
        return redirect

    monkeypatch.setattr(diag.urllib.request.HTTPHandler, "http_open", transport)
    result = asyncio.run(diag.get_run_events(RUN_ID))
    assert requests == [("http://agent:9099/diagnostics/runs/run_test1/events?limit=50",
                         "private-agent-token")]
    assert result["reason"] == "upstream_error" and result["reachability"] == "reachable"
    assert result["ownership"] == "unknown" and "attacker" not in json.dumps(result)


def test_body_bound_applies_before_parsing(setup, monkeypatch):
    reply = response(b"{" + b" " * (256 * 1024))
    stub_open(monkeypatch, lambda req, timeout: reply)
    result = asyncio.run(diag.get_run_events(RUN_ID))
    assert reply.read.call_args.args == (256 * 1024 + 1,)
    assert result["reason"] == "malformed_response"


def test_status_malformed_never_leaks(setup, monkeypatch):
    stub_open(monkeypatch, lambda req, timeout: response({"running": True, "currentRunId": ["secret"]}))
    result = asyncio.run(diag.get_agent_status())
    assert result["reason"] == "malformed_response" and "running" not in result
