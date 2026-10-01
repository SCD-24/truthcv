"""Tests for the run summary / bounded detail tools (api/diagnostics_runs.py)."""

from __future__ import annotations

import asyncio
import json

import pytest

import api.diagnostics_runs as dr
from api.diagnostics_mcp import _handle_diag_call_tool, _handle_diag_list_tools
from runs.model import RunRecord

RECOVERY = (
    "Stop acting on this posting, not the entire run; continue other work and "
    "coverage. Ask the operator to open GET /api/screenings."
)


class _Params:
    def __init__(self, name, arguments=None):
        self.name = name
        self.arguments = arguments or {}


def _seed(monkeypatch, record):
    monkeypatch.setattr(dr._runs_store, "get", lambda rid: record if rid == record.id else None)


def _run(**kw):
    return RunRecord(id="r1", **kw)


def test_list_runs_summaries_and_default_limit(monkeypatch):
    seen = {}

    def fake(limit, offset):
        seen["limit"] = limit
        return [
            _run(
                item_errors=["a", "b"],
                note="n",
                discovery_coverage=[{"status": "empty"}, {"status": "empty"}, {"status": "blocked"}],
            )
        ], 7

    monkeypatch.setattr(dr._runs_store, "list_page", fake)
    out = dr.list_runs()
    assert seen["limit"] == 20
    assert out["total"] == 7
    s = out["runs"][0]
    assert s["item_error_count"] == 2
    assert s["coverage_counts"] == {"empty": 2, "blocked": 1}
    for k in ("item_errors", "discovery_coverage", "note", "phase_refusals"):
        assert k not in s


def test_get_run_unknown(monkeypatch):
    monkeypatch.setattr(dr._runs_store, "get", lambda rid: None)
    assert dr.get_run("nope") == {}


def test_recovery_stripped_and_shown_once(monkeypatch):
    _seed(monkeypatch, _run(item_errors=[
        "Posting fetch failed. " + RECOVERY,
        "Other failed. " + RECOVERY,
        "plain " + "x" * 600,
    ]))
    out = dr.get_run("r1")
    assert out["item_errors"]["entries"][:2] == ["Posting fetch failed", "Other failed"]
    assert out["recovery_instruction"] == RECOVERY
    assert len(out["item_errors"]["entries"][2]) == 500


def test_truncated_recovery_still_strips(monkeypatch):
    _seed(monkeypatch, _run(item_errors=["Boom. " + RECOVERY[:60]]))
    out = dr.get_run("r1")
    assert out["item_errors"]["entries"] == ["Boom"]
    assert out["recovery_instruction"] == RECOVERY[:60]


def test_no_recovery_key_absent(monkeypatch):
    _seed(monkeypatch, _run(item_errors=["just an error"]))
    out = dr.get_run("r1")
    assert out["item_errors"]["entries"] == ["just an error"]
    assert "recovery_instruction" not in out


def test_recovery_found_beyond_current_page(monkeypatch):
    errors = [f"e{i}" for i in range(25)] + ["Late. " + RECOVERY]
    _seed(monkeypatch, _run(item_errors=errors))
    out = dr.get_run("r1")
    assert len(out["item_errors"]["entries"]) == 20
    assert out["recovery_instruction"] == RECOVERY


def test_malformed_coverage_entries_are_skipped(monkeypatch):
    record = _run(discovery_coverage=[None, {"status": "empty"}])
    _seed(monkeypatch, record)
    out = dr.get_run("r1")
    assert out["coverage_counts"] == {"empty": 1}
    assert out["discovery_coverage"]["total"] == 1


def test_errors_paging(monkeypatch):
    _seed(monkeypatch, _run(item_errors=[f"e{i}" for i in range(250)]))
    out = dr.get_run("r1")["item_errors"]
    assert len(out["entries"]) == 20 and out["next_offset"] == 20 and out["total"] == 250
    assert len(dr.get_run("r1", errors_limit=1000)["item_errors"]["entries"]) == 100
    assert dr.get_run("r1", errors_offset=-5)["item_errors"]["offset"] == 0
    off, seen = 0, 0
    while off is not None:
        page = dr.get_run("r1", errors_offset=off, errors_limit=100)["item_errors"]
        seen += len(page["entries"])
        off = page["next_offset"]
    assert seen == 250


def test_coverage_paging_filter_caps(monkeypatch):
    cov = [{"channel": "feed", "board": "b" * 300, "status": "empty",
            "postings_found": 0, "reason": "r" * 300} for _ in range(45)]
    cov += [{"channel": "direct", "board": "x", "status": "blocked", "postings_found": 0, "reason": ""}]
    _seed(monkeypatch, _run(discovery_coverage=cov))
    out = dr.get_run("r1")["discovery_coverage"]
    assert len(out["entries"]) == 20 and out["total"] == 46
    assert len(out["entries"][0]["board"]) == 200 and len(out["entries"][0]["reason"]) == 200
    assert out["entries"][0]["tier"] == ""
    assert len(dr.get_run("r1", coverage_limit=999)["discovery_coverage"]["entries"]) == 46
    filt = dr.get_run("r1", coverage_status="blocked")["discovery_coverage"]
    assert filt["total"] == 1 and filt["next_offset"] is None
    chain, off = 0, 0
    while off is not None:
        p = dr.get_run("r1", coverage_offset=off, coverage_limit=20)["discovery_coverage"]
        chain += 1
        off = p["next_offset"]
    assert chain == 3
    assert dr.get_run("r1", coverage_offset=-3)["discovery_coverage"]["offset"] == 0


def test_note_capped(monkeypatch):
    _seed(monkeypatch, _run(note="n" * 2500))
    out = dr.get_run("r1")
    assert len(out["note"]) == 2000 and out["note_length"] == 2500


def test_discovery_schema():
    result = asyncio.run(_handle_diag_list_tools(None, None))
    tool = next(t for t in result.tools if t.name == "get_run")
    assert tool.input_schema["required"] == ["run_id"]
    props = tool.input_schema["properties"]
    for k in ("errors_offset", "errors_limit", "coverage_offset", "coverage_limit"):
        assert props[k]["type"] == "integer"


def test_call_tool_output_is_compact(monkeypatch):
    monkeypatch.setattr(dr._runs_store, "list_page", lambda limit, offset: ([_run()], 1))
    result = asyncio.run(_handle_diag_call_tool(None, _Params("list_runs")))
    text = result.content[0].text
    assert not result.is_error, text
    assert ", " not in text and ": " not in text
    assert json.loads(text)["total"] == 1
