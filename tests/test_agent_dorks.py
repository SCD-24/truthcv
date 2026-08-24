"""Dork-query composer: query shape, source resolution, filtering, caps."""

from urllib.parse import unquote_plus

from agentconfig import dorks
from agentconfig.store import JobProfile


def test_multi_word_keyword_is_quoted_single_word_is_not():
    p = JobProfile(name="p", enabled=True, keywords=["platform engineer", "SRE"], preferred_sources=["ashby"])
    q = dorks.compose_queries([p])[0]["query"]
    assert '"platform engineer"' in q
    assert "SRE" in q
    assert '"SRE"' not in q


def test_multiple_keywords_and_locations_become_separate_or_groups():
    p = JobProfile(
        name="p",
        enabled=True,
        keywords=["backend", "platform"],
        locations=["Berlin", "Remote"],
        preferred_sources=["ashby"],
    )
    q = dorks.compose_queries([p])[0]["query"]
    assert "(backend OR platform)" in q
    assert "(Berlin OR Remote)" in q


def test_preferred_source_containing_dot_used_verbatim():
    p = JobProfile(name="p", enabled=True, keywords=["backend"], preferred_sources=["custom.example.com"])
    entries = dorks.compose_queries([p])
    assert len(entries) == 1
    assert entries[0]["source"] == "custom.example.com"
    assert entries[0]["query"].startswith("site:custom.example.com")


def test_known_source_name_maps_to_domain():
    p = JobProfile(name="p", enabled=True, keywords=["backend"], preferred_sources=["greenhouse"])
    entries = dorks.compose_queries([p])
    assert len(entries) == 1
    assert entries[0]["source"] == "job-boards.greenhouse.io"


def test_unknown_non_domain_source_is_skipped():
    p = JobProfile(name="p", enabled=True, keywords=["backend"], preferred_sources=["totallymadeup"])
    assert dorks.compose_queries([p]) == []


def test_empty_preferred_sources_falls_back_to_default_boards():
    p = JobProfile(name="p", enabled=True, keywords=["backend"], preferred_sources=[])
    entries = dorks.compose_queries([p])
    assert len(entries) == len(dorks.DEFAULT_BOARD_DOMAINS) == 4
    sources = {e["source"] for e in entries}
    assert sources == set(dorks.DEFAULT_BOARD_DOMAINS)


def test_rejected_role_types_render_as_negatives():
    p = JobProfile(
        name="p",
        enabled=True,
        keywords=["backend"],
        preferred_sources=["ashby"],
        rejected_role_types=["contract", "unpaid internship"],
    )
    q = dorks.compose_queries([p])[0]["query"]
    assert '-"contract"' in q
    assert '-"unpaid internship"' in q


def test_disabled_profile_produces_nothing():
    p = JobProfile(name="p", enabled=False, keywords=["backend"], preferred_sources=["ashby"])
    assert dorks.compose_queries([p]) == []


def test_empty_keywords_produces_nothing():
    p = JobProfile(name="p", enabled=True, keywords=[], preferred_sources=["ashby"])
    assert dorks.compose_queries([p]) == []


def test_url_is_percent_encoded_and_carries_recency_param():
    p = JobProfile(name="p", enabled=True, keywords=["platform engineer"], preferred_sources=["ashby"])
    entry = dorks.compose_queries([p])[0]
    assert "%22platform+engineer%22" in entry["url"] or "%22platform%20engineer%22" in entry["url"]
    assert entry["url"].endswith("&tbs=qdr:w")
    assert unquote_plus(entry["url"].split("q=")[1].split("&tbs=")[0]) == entry["query"]


def test_total_is_truncated_at_max_queries():
    profiles = [
        JobProfile(name=f"p{i}", enabled=True, keywords=["backend"], preferred_sources=[])
        for i in range(10)
    ]
    entries = dorks.compose_queries(profiles)
    assert len(entries) <= dorks.MAX_QUERIES
    assert len(entries) == dorks.MAX_QUERIES  # 10 profiles * 4 default sources = 40 > 24
