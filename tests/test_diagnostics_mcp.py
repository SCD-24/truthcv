"""Guard + behaviour tests for the read-only diagnostics MCP endpoint
(/mcp/diagnostics, api/diagnostics_mcp.py).

These pin down the two things that matter about a second, bearer-token-only
MCP surface: that it is unreachable without the right token (404, never a
hint-carrying 401/403), and that once authenticated it exposes only the
nine read-only diagnostics tools — never any tool from the operational
registry that can write.

The 404-gate tests use a bare ``TestClient(app)`` (no lifespan): the auth
check in api.main's /mcp/diagnostics route runs and rejects the request
*before* it ever reaches the MCP dispatch, so no active session manager is
needed.

The tools/list and tools/call tests exercise api.diagnostics_mcp's own
JSON-RPC handlers (`_handle_diag_list_tools` / `_handle_diag_call_tool`)
directly rather than over real HTTP. This is deliberate, not a shortcut for
its own sake: mcp.server.streamable_http's StreamableHTTPSessionManager.run()
can be entered at most ONCE per process for a given Server instance, and
tests/test_mcp_transport.py already owns the one process-wide
``with TestClient(app) as client:`` entry that activates it — a second entry
anywhere else (this file included) would raise and take that file's
existing, passing tests down with it. Calling the handlers directly
exercises exactly the same dispatch logic (registry lookup, schema, tool
invocation, error wrapping) without needing the streamable-HTTP transport's
task group at all. Handler tests run in an event loop because synchronous
store reads are now offloaded to a thread and supervisor reads are async.
"""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.diagnostics_mcp import (
    _DIAG_TOOL_REGISTRY,
    _clamp_limit,
    _handle_diag_call_tool,
    _handle_diag_list_tools,
)
from api.main import app
from gmailsync.model import GmailSuggestion, GmailSyncState


class _ToolCallParams:
    """Minimal duck-typed stand-in for mcp.types.CallToolRequestParams.

    `_handle_diag_call_tool` only ever reads `.name` and `.arguments` off
    its `params`, so a real (pydantic-validated) instance is unnecessary —
    this keeps these tests independent of the SDK's exact model shape.
    """

    def __init__(self, name: str, arguments: dict | None = None):
        self.name = name
        self.arguments = arguments or {}


def stub_agent_open(monkeypatch, open_url):
    import api.agent_diagnostics as diag

    monkeypatch.setattr(diag.urllib.request, "build_opener",
                        lambda *handlers: SimpleNamespace(open=open_url))


def _run_sync(coro):
    """Run a handler on a real loop so threaded store access is exercised."""
    return asyncio.run(coro)


def _rpc(client: TestClient, method: str, params: dict | None = None, headers: dict | None = None):
    return client.post(
        "/mcp/diagnostics",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers=headers or {},
    )


def test_no_authorization_header_is_404(data_dir, monkeypatch):
    monkeypatch.setenv("DIAGNOSTICS_MCP_TOKEN", "correct-token")
    client = TestClient(app)
    r = _rpc(client, "tools/list")
    assert r.status_code == 404


def test_wrong_token_is_404(data_dir, monkeypatch):
    monkeypatch.setenv("DIAGNOSTICS_MCP_TOKEN", "correct-token")
    client = TestClient(app)
    r = _rpc(client, "tools/list", headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 404


def test_unset_token_env_is_404_even_with_a_bearer_header(data_dir, monkeypatch):
    """Unset DIAGNOSTICS_MCP_TOKEN must match nothing, including an empty
    bearer value — matching diagnostics_token_ok's contract directly."""
    monkeypatch.delenv("DIAGNOSTICS_MCP_TOKEN", raising=False)
    client = TestClient(app)
    r = _rpc(client, "tools/list", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 404
    r_empty = _rpc(client, "tools/list", headers={"Authorization": "Bearer "})
    assert r_empty.status_code == 404


def test_correct_token_passes_the_auth_gate(data_dir, monkeypatch):
    """The accept path: a correct bearer token must get PAST the 404 gate.

    Without the app lifespan (deliberately not entered here — see the module
    docstring) the forwarded request fails inside the MCP transport with
    "Task group is not initialized" (a 500), which is exactly the evidence
    needed: the request was forwarded rather than short-circuited to 404.
    Without this test, the whole gate suite would pass against an endpoint
    that 404s unconditionally.
    """
    monkeypatch.setenv("DIAGNOSTICS_MCP_TOKEN", "correct-token")
    client = TestClient(app, raise_server_exceptions=False)
    r = _rpc(
        client,
        "tools/list",
        headers={"Authorization": "Bearer correct-token"},
    )
    assert r.status_code != 404


def test_existing_operational_mcp_endpoint_has_no_auth_gate(data_dir, monkeypatch):
    """/mcp itself must still require no Authorization header — the
    diagnostics endpoint's bearer-token gate must not leak onto it.

    A full JSON-RPC dispatch against /mcp needs the operational session
    manager's task group active (the app lifespan), which — for the reason
    explained at the top of this file — this test suite cannot start a
    second time. `raise_server_exceptions=False` lets us observe the
    resulting response instead of an uncaught exception: what matters here
    is only that the request is never short-circuited to 404, i.e. that no
    auth gate was added to /mcp.
    """
    monkeypatch.delenv("DIAGNOSTICS_MCP_TOKEN", raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert r.status_code != 404


def test_registry_holds_exactly_the_nine_read_only_tools():
    assert set(_DIAG_TOOL_REGISTRY) == {
        "list_runs",
        "get_run",
        "list_screenings",
        "list_applications",
        "get_status",
        "get_gmail_sync_status",
        "list_gmail_suggestions",
        "get_agent_status",
        "get_run_events",
    }


def test_tools_list_handler_advertises_exactly_the_nine_diagnostics_tools():
    result = _run_sync(_handle_diag_list_tools(None, None))
    names = {tool.name for tool in result.tools}
    assert names == {
        "list_runs",
        "get_run",
        "list_screenings",
        "list_applications",
        "get_status",
        "get_gmail_sync_status",
        "list_gmail_suggestions",
        "get_agent_status",
        "get_run_events",
    }
    # None of the operational, write-capable tools are reachable here.
    assert "record_application" not in names
    assert "record_screening" not in names
    assert "start_run" not in names
    assert "generate_cover_letter" not in names


def test_get_status_round_trips_through_the_call_tool_handler(data_dir):
    params = _ToolCallParams(name="get_status", arguments={})
    result = _run_sync(_handle_diag_call_tool(None, params))
    text = result.content[0].text
    assert not result.is_error, text
    payload = json.loads(text)
    assert "encryption_available" in payload
    assert "runs" in payload
    assert "gmail_suggestions" in payload
    assert "gmail_last_synced_at" in payload


def test_get_gmail_sync_status_round_trips_through_the_call_tool_handler(data_dir):
    import gmailsync.store as gmailsync_store

    gmailsync_store.save_sync_state(
        GmailSyncState(last_synced_at=1700000000.0, processed_message_ids=["m1", "m2", "m3"])
    )

    params = _ToolCallParams(name="get_gmail_sync_status", arguments={})
    result = _run_sync(_handle_diag_call_tool(None, params))
    text = result.content[0].text
    assert not result.is_error, text
    payload = json.loads(text)
    assert payload["last_synced_at"] == 1700000000.0
    assert payload["processed_message_count"] == 3


def test_list_gmail_suggestions_round_trips_seeded_suggestions_newest_first(data_dir):
    """Seeds real RFC-2822 Gmail `Date` headers, chosen so a lexicographic
    string sort would order them wrongly ("Wed" > "Fri"): only parsing the
    dates puts the 2025 suggestion first."""
    import gmailsync.store as gmailsync_store

    gmailsync_store.save_suggestions(
        [
            GmailSuggestion(id="g-old", date="Wed, 5 Jun 2024 09:00:00 +0000"),
            GmailSuggestion(id="g-new", date="Fri, 3 Jan 2025 10:00:00 +0000"),
        ]
    )

    params = _ToolCallParams(name="list_gmail_suggestions", arguments={})
    result = _run_sync(_handle_diag_call_tool(None, params))
    text = result.content[0].text
    assert not result.is_error, text
    payload = json.loads(text)
    assert payload["total"] == 2
    ids = [s["id"] for s in payload["suggestions"]]
    assert ids == ["g-new", "g-old"]


def test_list_runs_round_trips_a_seeded_run(data_dir):
    import runs.store as runs_store

    runs_store.start("diag-run-1", trigger="scheduled", apply_cap=0)

    params = _ToolCallParams(name="list_runs", arguments={})
    result = _run_sync(_handle_diag_call_tool(None, params))
    text = result.content[0].text
    assert not result.is_error, text
    payload = json.loads(text)
    assert any(r["id"] == "diag-run-1" for r in payload["runs"])


# --- _clamp_limit -----------------------------------------------------------


def test_clamp_limit_non_positive_yields_the_default():
    assert _clamp_limit(0) == 50
    assert _clamp_limit(-1) == 50
    assert _clamp_limit(None) == 50


def test_clamp_limit_caps_above_the_maximum():
    assert _clamp_limit(10000) == 200


def test_clamp_limit_passes_through_an_in_range_value():
    assert _clamp_limit(37) == 37


def test_list_screenings_sorts_by_created_at_falling_back_to_screened_date(monkeypatch):
    """Ordering is by created_at descending, not screened_date: a record with
    no screened_date (e.g. freshly recorded via record_screening before this
    fix, or a caller that genuinely has none) must still sort by when it was
    actually created, not fall to the bottom for want of a screened_date."""
    import api.diagnostics_mcp as diagnostics_mcp
    from screening.model import Screening

    older_with_screened_date = Screening(
        id="s-old",
        company="OldCo",
        role="Engineer",
        url="https://jobs.example.com/old",
        screened_date="2020-01-01",
        created_at="2020-01-01T00:00:00+00:00",
    )
    newer_with_empty_screened_date = Screening(
        id="s-new",
        company="NewCo",
        role="Engineer",
        url="https://jobs.example.com/new",
        screened_date="",
        created_at="2024-06-01T00:00:00+00:00",
    )

    monkeypatch.setattr(
        diagnostics_mcp._screening_store,
        "load_all",
        lambda: [older_with_screened_date, newer_with_empty_screened_date],
    )
    result = diagnostics_mcp.list_screenings()

    ids = [s["id"] for s in result["screenings"]]
    assert ids == ["s-new", "s-old"]


def test_list_runs_non_positive_limit_is_clamped_to_the_default_not_unbounded(
    data_dir, monkeypatch
):
    """A limit<=0 must apply _DEFAULT_LIST_LIMIT, not be treated as
    "no limit" — proven by lowering the default below the seeded record
    count and checking the page is bounded accordingly."""
    import api.diagnostics_mcp as diagnostics_mcp
    import runs.store as runs_store

    monkeypatch.setattr(diagnostics_mcp, "_DEFAULT_LIST_LIMIT", 2)
    for i in range(3):
        runs_store.start(f"diag-clamp-run-{i}", trigger="scheduled", apply_cap=0)

    params = _ToolCallParams(name="list_runs", arguments={"limit": -5})
    result = _run_sync(_handle_diag_call_tool(None, params))
    text = result.content[0].text
    assert not result.is_error, text
    payload = json.loads(text)
    assert payload["total"] == 3
    assert len(payload["runs"]) == 2


def test_list_gmail_suggestions_non_positive_limit_is_clamped_to_the_default_not_unbounded(
    data_dir, monkeypatch
):
    """Same guarantee as list_runs's clamp test, for list_gmail_suggestions:
    a limit<=0 must apply _DEFAULT_LIST_LIMIT, not be treated as "no
    limit"."""
    import api.diagnostics_mcp as diagnostics_mcp
    import gmailsync.store as gmailsync_store

    monkeypatch.setattr(diagnostics_mcp, "_DEFAULT_LIST_LIMIT", 2)
    gmailsync_store.save_suggestions(
        [GmailSuggestion(id=f"g-{i}", date=f"2024-01-0{i+1}T00:00:00+00:00") for i in range(3)]
    )

    params = _ToolCallParams(name="list_gmail_suggestions", arguments={"limit": -5})
    result = _run_sync(_handle_diag_call_tool(None, params))
    text = result.content[0].text
    assert not result.is_error, text
    payload = json.loads(text)
    assert payload["total"] == 3
    assert len(payload["suggestions"]) == 2


def test_producer_shaped_metadata_consumed_through_mcp(data_dir, monkeypatch):
    """Contract fixture follows harness/diagnostics.ts -> agent/diagnostics.mjs.

    One model start and terminal boundary, then an outer tool start, with
    the producer's camelCase supervisor ownership alongside snake_case
    event metadata. Only the explicit metadata fields may be returned.
    """
    import api.agent_diagnostics as diag
    import runs.store as runs_store

    run_id = "producer_run"
    runs_store.start(run_id, trigger="scheduled")
    at = "2023-11-14T22:13:20.000Z"
    active = {"operation_id": "op_2", "phase": "tool", "started_at": at,
              "tool_name": "screen_and_record_posting", "turn": 4}
    common = {"schema_version": 1, "run_id": run_id, "at": at,
              "active_truncated": False, "truncated": False}
    events = [
        {**common, "sequence": 1, "operation_id": "op_1", "phase": "model",
         "status": "start", "active_operations": [
             {"operation_id": "op_1", "phase": "model", "started_at": at}]},
        {**common, "sequence": 2, "operation_id": "op_1", "phase": "model",
         "status": "success", "duration_ms": 23, "active_operations": []},
        {**common, "sequence": 3, "operation_id": "op_2", "phase": "tool",
         "status": "start", "tool_name": "screen_and_record_posting", "turn": 4,
         "active_operations": [active]},
    ]
    page = {"schema_version": 1, "run_id": run_id, "running": True,
            "currentRunId": run_id, "observed_at": at, "availability": "available",
            "reason": None, "events": events, "next_before_sequence": None,
            "truncated": False, "last_activity_at": at, "active_operations": [active],
            "active_truncated": False}

    def open_url(req, timeout):
        assert req.get_method() == "GET"
        assert req.full_url == f"http://agent:9099/diagnostics/runs/{run_id}/events?limit=50"
        reply = MagicMock()
        reply.read.return_value = json.dumps(page).encode()
        reply.__enter__.return_value = reply
        return reply

    monkeypatch.setenv("AGENT_API_TOKEN", "agent-only-token")
    monkeypatch.setenv("AGENT_CONTROL_PORT", "9099")
    stub_agent_open(monkeypatch, open_url)
    result = _run_sync(_handle_diag_call_tool(None, _ToolCallParams("get_run_events", {"run_id": run_id})))
    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["ownership"] == "active" and payload["reachability"] == "reachable"
    assert [event["status"] for event in payload["events"]] == ["start", "success", "start"]
    assert payload["events"][1]["duration_ms"] == 23
    assert payload["active_operations"] == [active]
    assert payload["active_truncated"] is False
    assert "agent-only-token" not in result.content[0].text


def test_untrusted_live_telemetry_round_trips_through_mcp(data_dir, monkeypatch):
    import runs.store as runs_store

    run_id = 'untrusted_run'
    runs_store.start(run_id, trigger='scheduled')
    at = '2023-11-14T22:13:20.000Z'
    # Produced by the supervisor when a valid persisted active snapshot cannot
    # be trusted after write+unlink failure or a lost health lease.
    page = {'schema_version': 1, 'run_id': run_id, 'running': True,
            'currentRunId': run_id, 'observed_at': at, 'availability': 'unavailable',
            'reason': 'telemetry_unavailable', 'events': [], 'next_before_sequence': None,
            'truncated': False, 'last_activity_at': None, 'active_operations': [],
            'active_truncated': False}

    def open_url(req, timeout):
        reply = MagicMock()
        reply.read.return_value = json.dumps(page).encode()
        reply.__enter__.return_value = reply
        return reply

    monkeypatch.setenv('AGENT_API_TOKEN', 'agent-only-token')
    stub_agent_open(monkeypatch, open_url)
    result = _run_sync(_handle_diag_call_tool(None, _ToolCallParams('get_run_events', {'run_id': run_id})))
    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload['reason'] == 'telemetry_unavailable' and payload['ownership'] == 'active'
    assert payload['running'] is True and payload['currentRunId'] == run_id
    assert payload['events'] == payload['active_operations'] == []


def test_run_events_discovery_schema():
    schema = next(t.input_schema for t in _run_sync(_handle_diag_list_tools(None, None)).tools
                  if t.name == "get_run_events")
    assert set(schema["properties"]) == {"run_id", "limit", "before_sequence"}
    assert schema["required"] == ["run_id"]


def test_sync_tools_do_not_block_async_handler(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def slow_read():
        entered.set()
        release.wait(2)
        return {"ok": True}
    monkeypatch.setitem(_DIAG_TOOL_REGISTRY, "get_status", (slow_read, "read-only"))

    async def scenario():
        task = asyncio.create_task(_handle_diag_call_tool(None, _ToolCallParams("get_status")))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            # This coroutine must run while the store read is still blocked.
            assert not task.done()
        finally:
            release.set()
        return await task

    result = asyncio.run(asyncio.wait_for(scenario(), 3))
    assert json.loads(result.content[0].text) == {"ok": True}


def test_agent_network_probe_does_not_block_async_handler(data_dir, monkeypatch):
    import api.agent_diagnostics as diag

    entered, release = threading.Event(), threading.Event()
    def slow_probe(req, timeout):
        entered.set()
        release.wait(2)
        reply = MagicMock()
        reply.read.return_value = b'{"running":false,"currentRunId":null}'
        reply.__enter__.return_value = reply
        return reply
    monkeypatch.setenv("AGENT_API_TOKEN", "private-token")
    stub_agent_open(monkeypatch, slow_probe)

    async def scenario():
        task = asyncio.create_task(_handle_diag_call_tool(None, _ToolCallParams("get_agent_status")))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            assert not task.done()
        finally:
            release.set()
        return await task

    result = asyncio.run(asyncio.wait_for(scenario(), 3))
    assert json.loads(result.content[0].text)["running"] is False


def test_tool_errors_do_not_echo_secret_exception(monkeypatch):
    def fails():
        raise RuntimeError("secret: do not expose")
    monkeypatch.setitem(_DIAG_TOOL_REGISTRY, "get_status", (fails, "read-only"))
    result = _run_sync(_handle_diag_call_tool(None, _ToolCallParams("get_status")))
    assert result.is_error and "secret" not in result.content[0].text
