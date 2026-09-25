"""agenttools/tools_runs.py: finish_run's discovery-coverage guard.

The agent's first premature finish_run for a 'completed' run with short
direct/dork discovery coverage must fail loudly (ValueError, and as an
isError tool result through the MCP transport) so the model returns to
discovery; a second call always closes the run.
"""

from __future__ import annotations

import pytest

import agentconfig.dorks as dorks
import agentconfig.store as agentconfig_store
from agenttools import tools_runs
from runs import store as runs_store


def _patch_expected_counts(monkeypatch, direct_count: int, query_count: int) -> None:
    """Fix compose_direct_boards/compose_queries to return exactly these many
    entries, regardless of the (default, empty) agent config, so a test can
    control 'expected' without building real profiles/boards."""
    monkeypatch.setattr(
        dorks, "compose_direct_boards", lambda *a, **k: [{}] * direct_count
    )
    monkeypatch.setattr(dorks, "compose_queries", lambda *a, **k: [{}] * query_count)


def _cover(run_id: str, channel: str, board: str, status: str = "searched") -> None:
    tools_runs.record_discovery_coverage(
        run_id=run_id, channel=channel, board=board, status=status
    )


def test_complete_coverage_finishes_on_first_call(monkeypatch, data_dir):
    _patch_expected_counts(monkeypatch, direct_count=2, query_count=3)
    tools_runs.start_run("run-a")
    _cover("run-a", "direct", "BoardOne")
    _cover("run-a", "direct", "BoardTwo")
    _cover("run-a", "dork", "QueryOne")
    _cover("run-a", "dork", "QueryTwo")
    _cover("run-a", "dork", "QueryThree")

    result = tools_runs.finish_run(run_id="run-a", status="completed")

    assert result["recorded"] is True
    assert result["status"] == "completed"


def test_short_coverage_raises_then_second_call_finishes(monkeypatch, data_dir):
    _patch_expected_counts(monkeypatch, direct_count=2, query_count=3)
    tools_runs.start_run("run-b")
    _cover("run-b", "direct", "BoardOne")  # only 1 of 2

    with pytest.raises(ValueError) as excinfo:
        tools_runs.finish_run(
            run_id="run-b", status="completed", stopped_reason="turn limit"
        )
    assert "direct" in str(excinfo.value)
    assert "1/2" in str(excinfo.value)
    assert "Discovery is not finished" in str(excinfo.value)

    refused = runs_store.get("run-b")
    assert refused.finish_refused is True

    result = tools_runs.finish_run(
        run_id="run-b", status="completed", stopped_reason="turn limit"
    )
    assert result["recorded"] is True
    assert result["stopped_reason"] == "turn limit"


def test_skipped_entry_is_flagged_by_name(monkeypatch, data_dir):
    _patch_expected_counts(monkeypatch, direct_count=1, query_count=1)
    tools_runs.start_run("run-skip")
    _cover("run-skip", "direct", "BoardBlocked", status="skipped")
    _cover("run-skip", "dork", "QueryOne")

    with pytest.raises(ValueError) as excinfo:
        tools_runs.finish_run(run_id="run-skip", status="completed")
    assert "BoardBlocked" in str(excinfo.value)


def test_non_completed_status_never_raises(monkeypatch, data_dir):
    _patch_expected_counts(monkeypatch, direct_count=2, query_count=3)
    tools_runs.start_run("run-c")

    result = tools_runs.finish_run(run_id="run-c", status="failed")

    assert result["recorded"] is True
    assert result["status"] == "failed"


def test_config_load_error_does_not_raise(monkeypatch, data_dir):
    def _boom():
        raise RuntimeError("config store is on fire")

    monkeypatch.setattr(agentconfig_store, "load", _boom)
    tools_runs.start_run("run-d")

    result = tools_runs.finish_run(run_id="run-d", status="completed")

    assert result["recorded"] is True
    assert result["status"] == "completed"


def test_refused_finish_run_is_a_tool_error_via_mcp(monkeypatch, data_dir):
    """Through the MCP tools/call handler, a refused finish_run comes back as
    an isError tool result — the harness treats any non-isError finish_run as
    the run being closed.

    Calls the handler directly rather than POSTing /mcp: the app's
    streamable-HTTP session manager can only be started once per process,
    and tests/test_mcp_transport.py owns that single start.
    """
    import asyncio

    from mcp import types

    from api.main import _handle_call_tool

    _patch_expected_counts(monkeypatch, direct_count=2, query_count=3)
    tools_runs.start_run("run-mcp")
    _cover("run-mcp", "direct", "BoardOne")

    params = types.CallToolRequestParams(
        name="finish_run", arguments={"run_id": "run-mcp", "status": "completed"}
    )
    result = asyncio.run(_handle_call_tool(None, params))

    assert result.is_error is True
    assert "Discovery is not finished" in result.content[0].text
