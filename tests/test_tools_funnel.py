import pytest

import runs.store as runs_store
import runs.url_ledger as url_ledger
from agenttools.tools_funnel import record_source_funnel

ROW = {
    "source": "linkedin.com", "channel": "feed", "postings_seen": 7,
    "previously_screened": 1, "not_a_posting": 1, "duplicate": 1,
    "failed": 1, "for_review": 1, "rejected": 1, "blocked": 1,
}
TOTALS = {
    "postings_seen": 7, "previously_screened": 1, "not_a_posting": 1, "duplicate": 1,
    "failed": 1, "for_review": 1, "rejected": 1, "blocked": 1,
}
URL = {
    "url": "https://x.test/jobs/1", "outcome": "for_review", "detail": "",
    "sources": [{"source": "linkedin.com", "channel": "feed"}],
}


def test_valid_report_is_stored(data_dir):
    runs_store.start("r1")
    out = record_source_funnel("r1", [ROW], {**TOTALS}, [URL])
    assert out == {"recorded": True, "mismatches": [], "truncated": False}
    rec = runs_store.get("r1")
    assert rec.source_funnel[0]["source"] == "linkedin.com"
    assert rec.funnel_totals["postings_seen"] == 7
    entries, total = url_ledger.read("r1")
    assert total == 1 and entries[0]["url"] == URL["url"]
    assert not (data_dir / "runs.json").read_text().count(URL["url"])


def test_invalid_channel_and_outcome_and_counts(data_dir):
    runs_store.start("r1")
    with pytest.raises(ValueError):
        record_source_funnel("r1", [{**ROW, "channel": "rss"}])
    with pytest.raises(ValueError):
        record_source_funnel("r1", [ROW], urls=[{**URL, "outcome": "weird"}])
    with pytest.raises(ValueError):
        record_source_funnel("r1", [{**ROW, "failed": -1}])
    assert runs_store.get("r1").source_funnel == []


def test_unknown_run_and_empty_run_id(data_dir):
    assert record_source_funnel("nope", [ROW])["recorded"] is False
    assert record_source_funnel() == {"recorded": False}


def test_replace_not_append(data_dir):
    runs_store.start("r1")
    record_source_funnel("r1", [ROW], urls=[URL, {**URL, "url": "https://x.test/2"}])
    record_source_funnel("r1", [{**ROW, "source": "b.test"}], urls=[URL])
    rec = runs_store.get("r1")
    assert [r["source"] for r in rec.source_funnel] == ["b.test"]
    assert url_ledger.read("r1")[1] == 1


def test_mismatch_detected_server_side(data_dir):
    runs_store.start("r1")
    out = record_source_funnel("r1", [{**ROW, "postings_seen": 9}, ROW])
    assert out["mismatches"] == ["linkedin.com"]
    assert runs_store.get("r1").funnel_mismatches == ["linkedin.com"]


def test_totals_mismatch_flagged(data_dir):
    runs_store.start("r1")
    out = record_source_funnel("r1", [ROW], {"postings_seen": 7})
    assert out["mismatches"] == ["totals"]


def test_empty_funnel_stores_full_totals(data_dir):
    runs_store.start("r1")
    record_source_funnel("r1", [], {})
    totals = runs_store.get("r1").funnel_totals
    assert totals["postings_seen"] == 0 and len(totals) == 8


def test_invalid_url_sources_raise(data_dir):
    runs_store.start("r1")
    for bad in ("x", {"channel": "feed"}, {"source": "", "channel": "feed"},
                {"source": "a", "channel": "rss"}):
        with pytest.raises(ValueError):
            record_source_funnel("r1", [ROW], urls=[{**URL, "sources": [bad]}])
    for bad_list in (False, 0, {}, None):
        with pytest.raises(ValueError):
            record_source_funnel("r1", [ROW], urls=[{**URL, "sources": bad_list}])


def test_ledger_odd_run_ids_round_trip(data_dir):
    for rid in ("team.1", "../x"):
        url_ledger.write(rid, [URL])
        assert url_ledger.read(rid)[1] == 1
    assert url_ledger.read("other")[1] == 0
    with pytest.raises(ValueError):
        url_ledger.ledger_path("")


def test_ledger_cap_sets_truncated(data_dir):
    runs_store.start("r1")
    urls = [{**URL, "url": f"https://x.test/{i}"} for i in range(url_ledger.URL_LEDGER_CAP + 5)]
    out = record_source_funnel("r1", [ROW], urls=urls)
    assert out["truncated"] is True
    assert runs_store.get("r1").url_ledger_truncated is True
    assert url_ledger.read("r1", limit=0)[1] == url_ledger.URL_LEDGER_CAP


def test_ledger_read_filters_and_pages(data_dir):
    url_ledger.write("r1", [
        {**URL, "url": f"u{i}", "outcome": "rejected" if i % 2 else "for_review"}
        for i in range(6)
    ])
    entries, total = url_ledger.read("r1", outcome="rejected", limit=2, offset=1)
    assert total == 3 and [e["url"] for e in entries] == ["u3", "u5"]
    assert url_ledger.read("r1", source="other")[1] == 0


def test_ledger_read_filters_same_source_by_channel(data_dir):
    url_ledger.write("r1", [
        {**URL, "url": "a", "sources": [{"source": "x.com", "channel": "feed"}]},
        {**URL, "url": "b", "sources": [{"source": "x.com", "channel": "dork"}]},
    ])
    assert [e["url"] for e in url_ledger.read("r1", source="x.com", channel="feed")[0]] == ["a"]
    assert [e["url"] for e in url_ledger.read("r1", source="x.com", channel="dork")[0]] == ["b"]
    assert url_ledger.read("r1", source="x.com")[1] == 2
