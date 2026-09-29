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


def test_status_with_whitespace_and_case_is_still_refused(monkeypatch, data_dir):
    """'Completed ' must be refused just like 'completed': the store
    normalizes status via runs.model.validate_status (strip + casefold), so
    the guard must compare against that same normalization, not the raw
    string."""
    _patch_expected_counts(monkeypatch, direct_count=2, query_count=3)
    tools_runs.start_run("run-status-case")
    _cover("run-status-case", "direct", "BoardOne")

    with pytest.raises(ValueError) as excinfo:
        tools_runs.finish_run(run_id="run-status-case", status="Completed ")
    assert "direct" in str(excinfo.value)


def test_config_load_error_with_skipped_dork_still_refuses(monkeypatch, data_dir):
    """A config load/compose failure must only drop the count-vs-config
    comparison, never the skipped-entry check, which reads the record alone."""
    def _boom():
        raise RuntimeError("config store is on fire")

    monkeypatch.setattr(agentconfig_store, "load", _boom)
    tools_runs.start_run("run-cfg-skip")
    _cover("run-cfg-skip", "dork", "QueryBlocked", status="skipped")

    with pytest.raises(ValueError) as excinfo:
        tools_runs.finish_run(run_id="run-cfg-skip", status="completed")
    assert "QueryBlocked" in str(excinfo.value)


def test_turns_remaining_refuses_three_times_then_accepts(monkeypatch, data_dir):
    _patch_expected_counts(monkeypatch, direct_count=2, query_count=3)
    tools_runs.start_run("run-turns")
    _cover("run-turns", "direct", "BoardOne")

    for _ in range(3):
        with pytest.raises(ValueError):
            tools_runs.finish_run(
                run_id="run-turns", status="completed", turns_remaining=300
            )

    result = tools_runs.finish_run(
        run_id="run-turns", status="completed", turns_remaining=300
    )
    assert result["recorded"] is True


def test_turns_remaining_near_reserve_is_accepted_first_call(monkeypatch, data_dir):
    _patch_expected_counts(monkeypatch, direct_count=2, query_count=3)
    tools_runs.start_run("run-turns-low")
    _cover("run-turns-low", "direct", "BoardOne")

    result = tools_runs.finish_run(
        run_id="run-turns-low", status="completed", turns_remaining=2
    )
    assert result["recorded"] is True


def test_omitted_turns_remaining_keeps_one_shot_behavior(monkeypatch, data_dir):
    _patch_expected_counts(monkeypatch, direct_count=2, query_count=3)
    tools_runs.start_run("run-turns-omit")
    _cover("run-turns-omit", "direct", "BoardOne")

    with pytest.raises(ValueError):
        tools_runs.finish_run(run_id="run-turns-omit", status="completed")

    result = tools_runs.finish_run(run_id="run-turns-omit", status="completed")
    assert result["recorded"] is True


def test_skipped_feed_entry_refuses_even_with_complete_direct_and_dork(monkeypatch, data_dir):
    """feed has no expected-count config, so only its skipped entries can flag
    it, but a skipped feed entry must still refuse the finish even when direct
    and dork are fully covered."""
    _patch_expected_counts(monkeypatch, direct_count=1, query_count=1)
    tools_runs.start_run("run-feed-skip")
    _cover("run-feed-skip", "feed", "BoardFeed", status="skipped")
    _cover("run-feed-skip", "direct", "BoardOne")
    _cover("run-feed-skip", "dork", "QueryOne")

    with pytest.raises(ValueError) as excinfo:
        tools_runs.finish_run(run_id="run-feed-skip", status="completed", turns_remaining=100)
    assert "BoardFeed" in str(excinfo.value)
    assert "feed" in str(excinfo.value)


def test_harness_aware_refusal_message_does_not_promise_recording(monkeypatch, data_dir):
    """With turns_remaining >= 0 the guard keeps refusing while coverage is
    short and turns remain, so the message must not say a repeat call "will
    be recorded" the way the legacy one-shot message does."""
    _patch_expected_counts(monkeypatch, direct_count=2, query_count=3)
    tools_runs.start_run("run-harness-msg")
    _cover("run-harness-msg", "direct", "BoardOne")

    with pytest.raises(ValueError) as excinfo:
        tools_runs.finish_run(run_id="run-harness-msg", status="completed", turns_remaining=100)
    message = str(excinfo.value)
    assert "will be recorded" not in message
    assert "turns_remaining=100" in message
    assert "turn limit is NOT a valid stopped_reason" in message


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
