"""Tests for the read-only screening diagnostics tools."""

from __future__ import annotations

import asyncio

import pytest

import api.diagnostics_mcp as diagnostics_mcp
from screening.model import Screening


def _seed(monkeypatch, records):
    monkeypatch.setattr(diagnostics_mcp._screening_store, "load_all", lambda: records)


def _s(i, **kw):
    base = dict(id=f"s{i}", company="Co", role="Eng", url=f"https://x.example/{i}",
                created_at=f"2024-01-{i + 1:02d}T00:00:00+00:00")
    base.update(kw)
    return Screening(**base)


def _ids(result):
    return [s["id"] for s in result["screenings"]]


def test_url_contains_is_case_insensitive(monkeypatch):
    _seed(monkeypatch, [_s(1, url="https://Jobs.Example/A"), _s(2, url="https://other/b")])
    r = diagnostics_mcp.list_screenings(url_contains="JOBS.example")
    assert _ids(r) == ["s1"] and r["total"] == 1


def test_text_contains_is_case_insensitive(monkeypatch):
    _seed(monkeypatch, [_s(1, posting_text="We use Python"), _s(2, posting_text="Go only")])
    r = diagnostics_mcp.list_screenings(text_contains="pYTHON")
    assert _ids(r) == ["s1"]


@pytest.mark.parametrize("field,value", [
    ("screening_blocker", "expired"), ("verdict", "passed"),
    ("approval", "pending"), ("run_id", "r1"),
])
def test_exact_filters(monkeypatch, field, value):
    _seed(monkeypatch, [_s(1, **{field: value}), _s(2, **{field: value + "x"}), _s(3)])
    r = diagnostics_mcp.list_screenings(**{field: value})
    assert _ids(r) == ["s1"] and r["total"] == 1


def test_total_is_filtered_count_before_paging(monkeypatch):
    _seed(monkeypatch, [_s(i, verdict="passed") for i in range(5)] + [_s(9, verdict="rejected")])
    r = diagnostics_mcp.list_screenings(verdict="passed", limit=2, offset=1)
    assert r["total"] == 5 and len(r["screenings"]) == 2


def test_summary_has_length_not_preview(monkeypatch):
    _seed(monkeypatch, [_s(1, posting_text="abcd"), _s(2)])
    by_id = {s["id"]: s for s in diagnostics_mcp.list_screenings()["screenings"]}
    assert by_id["s1"]["posting_text_length"] == 4
    assert by_id["s2"]["posting_text_length"] == 0
    assert "posting_text_preview" not in by_id["s1"]
    assert "posting_text_truncated" not in by_id["s1"]


def test_default_page_size_is_twenty(monkeypatch):
    _seed(monkeypatch, [_s(i % 28) for i in range(30)])
    assert len(diagnostics_mcp.list_screenings()["screenings"]) == 20


def _text_screening(monkeypatch, text, sid="s1"):
    _seed(monkeypatch, [_s(1, id=sid, posting_text=text)])


def test_get_screening_paging_chain(monkeypatch):
    _text_screening(monkeypatch, "x" * 20)
    r = diagnostics_mcp.get_screening("s1", offset=0, limit=8)
    pt = r["posting_text"]
    assert pt == {"total_length": 20, "offset": 0, "text": "x" * 8, "next_offset": 8}
    assert "posting_text" not in r["screening"]
    got = pt["text"]
    while pt["next_offset"] is not None:
        pt = diagnostics_mcp.get_screening("s1", offset=pt["next_offset"], limit=8)["posting_text"]
        got += pt["text"]
    assert got == "x" * 20


def test_get_screening_limit_clamps(monkeypatch):
    _text_screening(monkeypatch, "y" * 30000)
    big = diagnostics_mcp.get_screening("s1", limit=999999)["posting_text"]
    assert len(big["text"]) == 20000 and big["next_offset"] == 20000
    for lim in (0, -3):
        d = diagnostics_mcp.get_screening("s1", limit=lim)["posting_text"]
        assert len(d["text"]) == 8000 and d["next_offset"] == 8000


def test_get_screening_negative_and_past_end_offsets(monkeypatch):
    _text_screening(monkeypatch, "hello")
    neg = diagnostics_mcp.get_screening("s1", offset=-5)["posting_text"]
    assert neg["offset"] == 0 and neg["text"] == "hello" and neg["next_offset"] is None
    past = diagnostics_mcp.get_screening("s1", offset=5)["posting_text"]
    assert past["text"] == "" and past["next_offset"] is None


def test_get_screening_unknown_id(monkeypatch):
    _seed(monkeypatch, [])
    assert diagnostics_mcp.get_screening("nope") == {}


def test_search_exact_offsets_and_case_insensitive(monkeypatch):
    _text_screening(monkeypatch, "Foo bar foo BAR FOO")
    r = diagnostics_mcp.search_screening_text("s1", "foo", context_chars=2)
    assert r["total_length"] == 19 and r["query"] == "foo"
    assert r["total_matches"] == 3 and r["truncated"] is False
    assert [m["offset"] for m in r["matches"]] == [0, 8, 16]
    assert r["matches"][0] == {"offset": 0, "context_start": 0, "context": "Foo b"}
    assert r["matches"][2]["context"] == "R FOO"
    assert r["matches"][2]["context_start"] == 14


def test_search_is_literal(monkeypatch):
    _text_screening(monkeypatch, "a.b axb")
    assert diagnostics_mcp.search_screening_text("s1", "a.b")["total_matches"] == 1


def test_search_max_matches_clamp_and_truncated(monkeypatch):
    _text_screening(monkeypatch, "a" * 100)
    r = diagnostics_mcp.search_screening_text("s1", "a", max_matches=3)
    assert len(r["matches"]) == 3 and r["total_matches"] == 100 and r["truncated"] is True
    r = diagnostics_mcp.search_screening_text("s1", "a", max_matches=1000)
    assert len(r["matches"]) == 50
    r = diagnostics_mcp.search_screening_text("s1", "a", max_matches=0)
    assert len(r["matches"]) == 20


def test_search_context_clamp(monkeypatch):
    _text_screening(monkeypatch, "z" * 5000 + "needle" + "z" * 5000)
    big = diagnostics_mcp.search_screening_text("s1", "needle", context_chars=99999)
    assert len(big["matches"][0]["context"]) == 6 + 2000
    dflt = diagnostics_mcp.search_screening_text("s1", "needle", context_chars=0)
    assert len(dflt["matches"][0]["context"]) == 6 + 400


def test_search_blank_query_and_unknown_id(monkeypatch):
    _text_screening(monkeypatch, "abc")
    assert diagnostics_mcp.search_screening_text("s1", "  ") == {"error": "query must be non-empty"}
    assert diagnostics_mcp.search_screening_text("zz", "a") == {}


def test_discovery_schema_for_new_tools():
    tools = asyncio.run(diagnostics_mcp._handle_diag_list_tools(None, None)).tools
    schemas = {t.name: t.input_schema for t in tools}
    gs = schemas["get_screening"]
    assert gs["required"] == ["screening_id"]
    assert gs["properties"]["offset"]["type"] == "integer"
    assert gs["properties"]["limit"]["type"] == "integer"
    ss = schemas["search_screening_text"]
    assert ss["required"] == ["screening_id", "query"]
    assert ss["properties"]["context_chars"]["type"] == "integer"
    assert ss["properties"]["max_matches"]["type"] == "integer"
