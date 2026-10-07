import runs.store as runs_store
from agenttools import mcp_app
from agenttools.tools_pipeline import filter_unscreened_urls, finish_application
from screening import store as screening_store


def test_filter_unscreened_urls(data_dir):
    screening_store.create_or_get(
        {
            "company": "Acme",
            "role": "Engineer",
            "url": "https://example.com/jobs/1",
            "verdict": "rejected",
        }
    )
    out = filter_unscreened_urls(
        [
            "https://example.com/jobs/2#a",
            "https://example.com/jobs/1#frag",
            "https://example.com/jobs/3",
            "https://example.com/jobs/2#b",
        ]
    )
    assert out["unscreened"] == ["https://example.com/jobs/2", "https://example.com/jobs/3"]
    assert filter_unscreened_urls() == {"unscreened": [], "dropped": []}


def _enable_profiles(*names):
    from agentconfig.store import AgentConfig, JobProfile, save

    save(AgentConfig(profiles=[JobProfile(name=n, enabled=True) for n in names]))


def test_filter_unscreened_urls_rejected_for_one_profile_only(data_dir):
    _enable_profiles("A", "B")
    url = "https://example.com/jobs/9"
    screening_store.create_or_get(
        {"company": "Acme", "role": "E", "url": url, "verdict": "rejected", "profile": "A"}
    )
    assert filter_unscreened_urls([url])["unscreened"] == [url]


def test_filter_unscreened_urls_pass_under_one_profile_is_screened(data_dir):
    _enable_profiles("A", "B")
    url = "https://example.com/jobs/9"
    screening_store.create_or_get(
        {
            "company": "Acme", "role": "E", "url": url, "verdict": "deferred",
            "profile": "A",
        }
    )
    assert filter_unscreened_urls([url])["unscreened"] == []


def test_filter_unscreened_urls_dedupes_on_posting_key(data_dir):
    from agenttools.tools_pipeline import filter_unscreened_urls

    got = filter_unscreened_urls(
        ["https://EXAMPLE.com/jobs/2/", "https://example.com/jobs/2"]
    )
    assert got["unscreened"] == ["https://EXAMPLE.com/jobs/2/"]


def test_filter_unscreened_urls_drops_linkedin_search():
    spam = "https://ie.linkedin.com/jobs/%E6%B5%99-jobs?position=1&pageNum=0"
    assert filter_unscreened_urls([spam])["unscreened"] == []


def test_filter_unscreened_urls_collapses_linkedin_subdomains(data_dir):
    got = filter_unscreened_urls(
        [
            "https://uk.linkedin.com/jobs/view/555",
            "https://www.linkedin.com/jobs/view/title-555",
        ]
    )
    assert got["unscreened"] == ["https://uk.linkedin.com/jobs/view/555"]


def test_filter_unscreened_urls_screened_www_filters_uk(data_dir):
    screening_store.create_or_get(
        {
            "company": "Acme",
            "role": "E",
            "url": "https://www.linkedin.com/jobs/view/777",
            "verdict": "rejected",
        }
    )
    got = filter_unscreened_urls(["https://uk.linkedin.com/jobs/view/777"])
    assert got["unscreened"] == []


def test_filter_unscreened_urls_reports_dropped_reasons(data_dir):
    screening_store.create_or_get(
        {"company": "A", "role": "E", "url": "https://example.com/jobs/1", "verdict": "rejected"}
    )
    inputs = [
        "https://example.com/jobs/1#x",
        "https://example.com/jobs/2",
        "https://EXAMPLE.com/jobs/2/",
        "https://ie.linkedin.com/jobs/%E6%B5%99-jobs?position=1",
        "#frag",
        "",
        5,
    ]
    out = filter_unscreened_urls(inputs)
    assert out["unscreened"] == ["https://example.com/jobs/2"]
    by_url = {d["url"]: d for d in out["dropped"]}
    assert by_url["https://example.com/jobs/1"] == {
        "url": "https://example.com/jobs/1", "reason": "previously_screened"
    }
    dup = by_url["https://EXAMPLE.com/jobs/2/"]
    assert dup["reason"] == "duplicate"
    assert dup["duplicate_of"] == "https://example.com/jobs/2"
    assert {d["reason"] for d in out["dropped"]} == {
        "previously_screened", "duplicate", "not_a_posting"
    }
    non_empty = [u for u in inputs if isinstance(u, str) and u]
    assert len(out["unscreened"]) + len(out["dropped"]) == len(non_empty)


def test_finish_application_appends_note_without_status_change(data_dir):
    runs_store.start("r1", trigger="manual", apply_cap=1)
    before = runs_store.get("r1").status
    out = finish_application("r1", "https://x.test/j", "submitted", "ok")
    assert out["ok"] is True
    rec = runs_store.get("r1")
    assert rec.status == before
    assert "https://x.test/j" in rec.note and "submitted" in rec.note


def test_finish_application_noop_without_run_id(data_dir):
    out = finish_application()
    assert out["ok"] is True and "reason" in out


def test_tools_registered():
    assert "filter_unscreened_urls" in mcp_app._TOOL_REGISTRY
    assert "finish_application" in mcp_app._TOOL_REGISTRY
    for name in ("filter_unscreened_urls", "finish_application"):
        schema = mcp_app._input_schema(mcp_app._TOOL_REGISTRY[name][0])
        assert schema["required"] == []
