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
    assert out == {
        "unscreened": ["https://example.com/jobs/2", "https://example.com/jobs/3"]
    }
    assert filter_unscreened_urls() == {"unscreened": []}


def test_filter_unscreened_urls_dedupes_on_posting_key(data_dir):
    from agenttools.tools_pipeline import filter_unscreened_urls

    got = filter_unscreened_urls(
        ["https://EXAMPLE.com/jobs/2/", "https://example.com/jobs/2"]
    )
    assert got == {"unscreened": ["https://EXAMPLE.com/jobs/2/"]}


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
