"""Unit tests for the HTTP-facing run services and the supervisor client."""

from __future__ import annotations

import io
import urllib.error
from types import SimpleNamespace

import pytest

from truthcv.services import runs as svc
from truthcv.services import supervisor as sup
from truthcv.services.errors import (
    BadGateway,
    BadRequest,
    Conflict,
    InternalError,
    NotFound,
    ServiceError,
    Unavailable,
)


def _rec(run_id="r1", status="running"):
    return SimpleNamespace(id=run_id, status=status, to_dict=lambda: {"id": run_id, "status": status})


@pytest.fixture
def fake_store(monkeypatch):
    """Runs store with one run, and derivation stores that fail to load so the
    stored record is served as-is."""
    records = {"r1": _rec("r1", "running"), "done": _rec("done", "finished")}
    calls = {"finish": []}
    monkeypatch.setattr(svc._runs_store, "get", lambda rid: records.get(rid))
    monkeypatch.setattr(
        svc._runs_store, "list_page", lambda limit, offset: (list(records.values()), 2)
    )

    def finish(rid, status, stopped_reason=""):
        calls["finish"].append((rid, status, stopped_reason))
        return _rec(rid, "failed")

    monkeypatch.setattr(svc._runs_store, "finish_if_running", finish)

    def boom():
        raise RuntimeError("no store")

    monkeypatch.setattr(svc._screening_store, "load_all", boom)
    return calls


def test_list_runs_page_and_get_run_return_dicts(fake_store):
    rows, total = svc.list_runs_page(50, 0)
    assert total == 2
    assert [r["id"] for r in rows] == ["r1", "done"]
    assert svc.get_run("r1") == {"id": "r1", "status": "running"}


def test_get_run_unknown_is_not_found(fake_store):
    with pytest.raises(NotFound, match="^run not found$"):
        svc.get_run("nope")


def test_url_ledger_errors_and_clamps(fake_store, monkeypatch):
    with pytest.raises(NotFound, match="^run not found$"):
        svc.url_ledger_page("nope")
    with pytest.raises(BadRequest, match="^unknown outcome$"):
        svc.url_ledger_page("r1", outcome="bogus")
    with pytest.raises(BadRequest, match="^unknown channel$"):
        svc.url_ledger_page("r1", channel="bogus")

    seen = {}

    def fake_read(*args):
        seen["args"] = args
        return [], 0

    monkeypatch.setattr(svc._url_ledger, "read", fake_read)
    assert svc.url_ledger_page("r1", "src", "", 9999, -5, "feed") == ([], 0)
    assert seen["args"] == ("r1", "src", "", svc.URL_LEDGER_MAX_LIMIT, 0, "feed")
    svc.url_ledger_page("r1", limit=0)
    assert seen["args"][3] == 1


def test_stop_run_errors(fake_store):
    with pytest.raises(NotFound, match="^run not found$"):
        svc.stop_run("nope")
    with pytest.raises(Conflict, match="^run is not running$") as ei:
        svc.stop_run("done")
    assert ei.value.payload == "run is not running"


def test_stop_run_cancels_when_supervisor_owns_run(fake_store, monkeypatch):
    sent = []

    def fwd(path, method="GET"):
        sent.append((path, method))
        return {"running": True, "currentRunId": "r1"}

    monkeypatch.setattr(sup, "forward_to_supervisor", fwd)
    assert svc.stop_run("r1")[0] == "cancelling"
    assert sent == [("/status", "GET"), ("/cancel", "POST")]
    assert fake_store["finish"] == []


@pytest.mark.parametrize("exc", [Unavailable("down"), BadGateway("bad"), InternalError("tok")])
def test_stop_run_closes_orphan_when_supervisor_unreachable(fake_store, monkeypatch, exc):
    def fwd(path, method="GET"):
        raise exc

    monkeypatch.setattr(sup, "forward_to_supervisor", fwd)
    outcome, run = svc.stop_run("r1")
    assert (outcome, run["status"]) == ("closed", "failed")
    assert fake_store["finish"] == [("r1", "failed", "orphaned")]


def test_reconcile_passes_live_run_id_and_tolerates_unreachable(monkeypatch):
    got = []
    monkeypatch.setattr(
        svc._runs_store, "close_orphaned", lambda except_run_id: got.append(except_run_id) or []
    )
    monkeypatch.setattr(
        sup, "forward_to_supervisor", lambda p, method="GET": {"running": True, "currentRunId": "x"}
    )
    svc.reconcile_orphaned_runs()

    def down(p, method="GET"):
        raise Unavailable("Agent service unreachable")

    monkeypatch.setattr(sup, "forward_to_supervisor", down)
    svc.reconcile_orphaned_runs()
    assert got == ["x", None]


def test_supervisor_missing_token_is_internal_error(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "  ")
    with pytest.raises(InternalError, match="^AGENT_API_TOKEN is not set on the app service"):
        sup.forward_to_supervisor("/status")


def _http_error(code):
    return urllib.error.HTTPError("u", code, "m", {}, io.BytesIO(b""))


@pytest.mark.parametrize("code", [401, 403])
def test_supervisor_token_refusal_is_bad_gateway(monkeypatch, code):
    monkeypatch.setenv("AGENT_API_TOKEN", "t")

    def urlopen(req, timeout):
        raise _http_error(code)

    monkeypatch.setattr(sup.urllib.request, "urlopen", urlopen)
    with pytest.raises(BadGateway, match=rf"refused the request \(HTTP {code}\)"):
        sup.forward_to_supervisor("/status")


def test_supervisor_other_http_error_and_unreachable(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "t")

    def http500(req, timeout):
        raise _http_error(500)

    monkeypatch.setattr(sup.urllib.request, "urlopen", http500)
    with pytest.raises(BadGateway) as ei:
        sup.forward_to_supervisor("/status")
    assert str(ei.value) == "Agent service returned HTTP 500 for /status"

    def refused(req, timeout):
        raise urllib.error.URLError("nope")

    monkeypatch.setattr(sup.urllib.request, "urlopen", refused)
    with pytest.raises(Unavailable) as ei:
        sup.forward_to_supervisor("/status")
    assert str(ei.value) == "Agent service unreachable"
    assert issubclass(Unavailable, ServiceError)


def test_supervisor_success_sends_token_and_timeout(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "t")
    monkeypatch.setenv("AGENT_CONTROL_PORT", "1234")
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        seen.update(url=req.full_url, method=req.get_method(), tok=req.get_header("X-agent-token"), timeout=timeout)
        return Resp(b'{"running": false}')

    monkeypatch.setattr(sup.urllib.request, "urlopen", urlopen)
    assert sup.forward_to_supervisor("/cancel", method="POST") == {"running": False}
    assert seen == {"url": "http://agent:1234/cancel", "method": "POST", "tok": "t", "timeout": 10}
