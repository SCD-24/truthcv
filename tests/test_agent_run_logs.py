"""Fail-closed API contract for the agent's classified run-log projection."""

import asyncio
import json
import socket
import threading
import urllib.error
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api import agent_diagnostics as transport
from api import agent_run_logs as logs
from runs import store as runs_store

RUN_ID = "run_test1"
AT = "2023-11-14T22:13:20.000Z"
SECRET = "private@example.com https://private.example/?token=secret"


@pytest.fixture
def setup(data_dir, monkeypatch):
    runs_store.start(RUN_ID, trigger="scheduled")
    monkeypatch.setenv("AGENT_API_TOKEN", "private-agent-token")
    monkeypatch.setenv("AGENT_CONTROL_PORT", "9099")


def excerpt(category="provider_http", offset=123, **fields):
    defaults = {"provider_http": {"provider": "openai", "http_status": 429},
                "provider_network": {"provider": "anthropic"},
                "loop_event": {"kind": "retry"}, "harness_exit": {"exit_code": 3}}
    return {"offset": offset, "observed_at": AT, "category": category,
            "summary": logs._SUMMARIES[category], **defaults.get(category, {}), **fields}


def page(excerpts=None, **fields):
    return {"schema_version": 1, "run_id": RUN_ID, "availability": "available",
            "reason": None, "excerpts": [excerpt()] if excerpts is None else excerpts,
            "next_before_offset": None, "truncated": False, "omitted": False, **fields}


def response(data):
    reply = MagicMock()
    reply.read.return_value = json.dumps(data).encode() if not isinstance(data, bytes) else data
    reply.__enter__.return_value = reply
    reply.__exit__.return_value = False
    return reply


def stub_open(monkeypatch, opener):
    monkeypatch.setattr(transport.urllib.request, "build_opener",
                        lambda *handlers: SimpleNamespace(open=opener))


def read(*args, **kwargs):
    return asyncio.run(logs.get_run_logs(*args, **kwargs))


def test_get_fixed_transport_and_filtered_pagination(setup, monkeypatch):
    captured = {}

    def open_url(req, timeout):
        captured.update(url=req.full_url, method=req.get_method(), timeout=timeout,
                        token=req.get_header("X-agent-token"))
        return response(page([excerpt("provider_http", 120, retryable=True, retry_after_ms=1200),
                              excerpt("precondition", 100)],
                             next_before_offset=100, truncated=True, omitted=True))

    stub_open(monkeypatch, open_url)
    result = read(RUN_ID, 2, 200)
    assert captured == {"url": "http://agent:9099/diagnostics/runs/run_test1/logs?limit=2&before_offset=200",
                        "method": "GET", "timeout": 5, "token": "private-agent-token"}
    assert result["reachability"] == "reachable" and result["availability"] == "available"
    assert result["next_before_offset"] == 100 and result["omitted"] is True
    assert [e["summary"] for e in result["excerpts"]] == ["Provider HTTP error", "Agent precondition failed"]
    assert result["excerpts"][0]["retry_after_ms"] == 1200
    assert "private-agent-token" not in json.dumps(result)


def test_all_categories_and_finite_values(setup, monkeypatch):
    categories = list(logs._SUMMARIES)
    items = [excerpt(category, len(categories) - index) for index, category in enumerate(categories)]
    items[6].update(retryable=False, retry_after_ms=0)
    items[7].update(retryable=True, retry_after_ms=3_600_000, provider="openai_responses", http_status=599)
    items[8].update(retryable=False, provider="ollama")
    items[9].update(kind="emptyTurn", turn=1_000_000)
    items[10].update(stop_reason="turnCapReached", turns=1_000_000, exit_code=255)
    stub_open(monkeypatch, lambda req, timeout: response(page(items)))
    result = read(RUN_ID)
    assert result["availability"] == "available"
    assert [e["category"] for e in result["excerpts"]] == categories
    assert [e["summary"] for e in result["excerpts"]] == [logs._SUMMARIES[c] for c in categories]


@pytest.mark.parametrize("run_id,limit,before,reason", [
    ("../secret", 50, None, "invalid_request"), ([RUN_ID], 50, None, "invalid_request"),
    (RUN_ID, True, None, "invalid_request"), (RUN_ID, 0, None, "invalid_request"),
    (RUN_ID, 201, None, "invalid_request"), (RUN_ID, 50, False, "invalid_request"),
    (RUN_ID, 50, 0, "invalid_request"), ("absent", 50, None, "unknown_run"),
])
def test_rejects_bad_inputs_and_unknown_run_without_request(setup, monkeypatch, run_id, limit, before, reason):
    stub_open(monkeypatch, lambda *args, **kwargs: pytest.fail("unexpected HTTP request"))
    result = read(run_id, limit, before)
    assert result["reason"] == reason and result["reachability"] == "unknown"
    assert result["run_id"] == (run_id if isinstance(run_id, str) and run_id != "../secret" else None)
    assert SECRET not in json.dumps(result)


def test_store_read_and_network_are_offloaded(setup, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original_get = runs_store.get

    def slow_get(run_id):
        entered.set()
        release.wait(2)
        return original_get(run_id)

    monkeypatch.setattr(runs_store, "get", slow_get)
    stub_open(monkeypatch, lambda req, timeout: response(page()))

    async def scenario():
        task = asyncio.create_task(logs.get_run_logs(RUN_ID))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            assert not task.done()
        finally:
            release.set()
        return await task

    assert asyncio.run(asyncio.wait_for(scenario(), 3))["availability"] == "available"


@pytest.mark.parametrize("failure,reason,reachability", [
    (urllib.error.HTTPError("url", 403, SECRET, None, None), "token_mismatch", "reachable"),
    (urllib.error.HTTPError("url", 404, SECRET, None, None), "old_endpoint", "reachable"),
    (urllib.error.HTTPError("url", 500, SECRET, None, None), "upstream_error", "reachable"),
    (urllib.error.URLError(SECRET), "unreachable", "unreachable"),
    (socket.timeout(SECRET), "timeout", "unreachable"),
])
def test_transport_failures_never_echo_upstream(setup, monkeypatch, failure, reason, reachability):
    def fail(req, timeout):
        raise failure
    stub_open(monkeypatch, fail)
    result = read(RUN_ID)
    assert result["reason"] == reason and result["reachability"] == reachability
    assert SECRET not in json.dumps(result) and result["excerpts"] == []


def test_missing_token_never_requests(setup, monkeypatch):
    monkeypatch.delenv("AGENT_API_TOKEN")
    stub_open(monkeypatch, lambda *args, **kwargs: pytest.fail("unexpected HTTP request"))
    assert read(RUN_ID)["reason"] == "missing_token"


def test_redirect_is_denied_before_token_can_be_forwarded(setup, monkeypatch):
    monkeypatch.setattr(transport.urllib.request, "getproxies", lambda: {})
    requests = []

    def redirect(self, req):
        requests.append((req.full_url, req.get_header("X-agent-token")))
        reply = MagicMock()
        reply.code = 302
        reply.msg = "Found"
        reply.info.return_value = {"Location": "http://attacker.invalid/collect"}
        return reply

    monkeypatch.setattr(transport.urllib.request.HTTPHandler, "http_open", redirect)
    result = read(RUN_ID)
    assert requests == [("http://agent:9099/diagnostics/runs/run_test1/logs?limit=50", "private-agent-token")]
    assert result["reason"] == "upstream_error" and "attacker" not in json.dumps(result)


def test_read_bound_and_invalid_json(setup, monkeypatch):
    reply = response(b"{" + b" " * (256 * 1024))
    stub_open(monkeypatch, lambda req, timeout: reply)
    assert read(RUN_ID)["reason"] == "malformed_response"
    assert reply.read.call_args.args == (256 * 1024 + 1,)
    stub_open(monkeypatch, lambda req, timeout: response(b"{" + SECRET.encode()))
    assert read(RUN_ID)["reason"] == "malformed_response"


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(secret=SECRET),
    lambda p: p.update(run_id="another_run"),
    lambda p: p.update(schema_version=True),
    lambda p: p.update(availability=["available"]),
    lambda p: p.update(reason=SECRET),
    lambda p: p.update(excerpts=[excerpt(offset=10), excerpt(offset=11)]),
    lambda p: p.update(excerpts=[excerpt(offset=10), excerpt(offset=10)]),
    lambda p: p.update(excerpts=[excerpt(offset=20), excerpt(offset=10)], next_before_offset=15, truncated=True),
    lambda p: p.update(excerpts=[excerpt(offset=20)], next_before_offset=21, truncated=True),
    lambda p: p.update(excerpts=[], next_before_offset=200, truncated=True),
    lambda p: p.update(excerpts=[excerpt()] * 201),
    lambda p: p.update(truncated=True),
    lambda p: p.update(omitted=SECRET),
    lambda p: p.update(excerpts=[{**excerpt(), "raw": SECRET}]),
    lambda p: p.update(excerpts=[{**excerpt(), "summary": SECRET}]),
    lambda p: p.update(excerpts=[{**excerpt(), "provider": SECRET}]),
    lambda p: p.update(excerpts=[{**excerpt(), "http_status": True}]),
    lambda p: p.update(excerpts=[{**excerpt(), "http_status": 600}]),
    lambda p: p.update(excerpts=[{**excerpt(), "retry_after_ms": -1}]),
    lambda p: p.update(excerpts=[{**excerpt(), "retryable": SECRET}]),
    lambda p: p.update(excerpts=[{**excerpt(), "offset": True}]),
    lambda p: p.update(excerpts=[{**excerpt(), "offset": 2**53}]),
    lambda p: p.update(excerpts=[{**excerpt(), "observed_at": "2023-02-30T00:00:00.000Z"}]),
    lambda p: p.update(excerpts=[excerpt(offset=20), excerpt("done", 10, observed_at="2024-01-01T00:00:00.000Z")]),
    lambda p: p.update(excerpts=[{**excerpt(), "kind": "retry"}]),
    lambda p: p.update(excerpts=[{**excerpt("provider_network"), "http_status": 429}]),
    lambda p: p.update(excerpts=[{**excerpt("loop_event"), "kind": SECRET}]),
    lambda p: p.update(excerpts=[{**excerpt("done"), "stop_reason": SECRET}]),
    lambda p: p.update(excerpts=[{**excerpt("harness_exit"), "exit_code": 256}]),
    lambda p: p.update(excerpts=[{**excerpt("done"), "turns": True}]),
    lambda p: p.update(excerpts=[{**excerpt("harness_error"), "provider": "openai"}]),
    lambda p: p.update(excerpts=[{**excerpt(), "category": SECRET}]),
])
def test_malicious_payloads_fail_closed(setup, monkeypatch, mutate):
    payload = page()
    mutate(payload)
    stub_open(monkeypatch, lambda req, timeout: response(payload))
    result = read(RUN_ID, before_offset=150)
    assert result["reason"] == "malformed_response" and result["excerpts"] == []
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(secret=SECRET), lambda p: p.update(reason=SECRET),
    lambda p: p.update(excerpts=[excerpt()]), lambda p: p.update(next_before_offset=1),
    lambda p: p.update(truncated=True), lambda p: p.update(omitted=True),
    lambda p: p.update(reason=None),
])
def test_unavailable_invariants_fail_closed(setup, monkeypatch, mutate):
    payload = page([], availability="unavailable", reason="missing")
    mutate(payload)
    stub_open(monkeypatch, lambda req, timeout: response(payload))
    assert read(RUN_ID)["reason"] == "malformed_response"


def test_missing_unreadable_and_empty_filtered_pages(setup, monkeypatch):
    for reason in ("missing", "unreadable"):
        stub_open(monkeypatch, lambda req, timeout: response(page([], availability="unavailable", reason=reason)))
        assert read(RUN_ID)["reason"] == reason
    stub_open(monkeypatch, lambda req, timeout: response(page([], next_before_offset=50,
                                                              truncated=True, omitted=True)))
    result = read(RUN_ID, before_offset=100)
    assert result["availability"] == "available" and result["excerpts"] == []
    assert result["next_before_offset"] == 50 and result["omitted"] is True
