"""Dork-query composer: query shape, source resolution, filtering, caps."""

from datetime import date
from urllib.parse import parse_qs, unquote_plus, urlparse

import pytest

from agentconfig import boards as boards_module
from agentconfig import dorks
from agentconfig.store import JobBoard, JobProfile


def test_multi_word_keyword_is_quoted_single_word_is_not():
    p = JobProfile(name="p", enabled=True, title_keywords=["platform engineer", "SRE"])
    q = dorks.compose_queries([p], None, ["ashby"])[0]["query"]
    assert '"platform engineer"' in q
    assert "SRE" in q
    assert '"SRE"' not in q


def test_multiple_keywords_and_locations_become_separate_or_groups():
    p = JobProfile(
        name="p",
        enabled=True,
        keywords=["backend", "platform"],
        locations=["Berlin", "Remote"],
    )
    q = dorks.compose_queries([p], None, ["ashby"])[0]["query"]
    assert "(backend OR platform)" in q
    assert "(Berlin OR Remote)" in q


def test_preferred_source_containing_dot_used_verbatim():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    sources = ["ashby", "greenhouse", "lever", "workday", "custom.example.com"]
    entries = dorks.compose_queries([p], None, sources)
    # 4 defaults + the custom domain.
    assert len(entries) == 5
    custom = next(e for e in entries if e["source"] == "custom.example.com")
    assert custom["query"].startswith("site:custom.example.com")


def test_known_source_name_maps_to_domain():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    # "greenhouse" repeated alongside the other defaults is not duplicated.
    sources = ["ashby", "greenhouse", "lever", "workday", "greenhouse"]
    entries = dorks.compose_queries([p], None, sources)
    assert len(entries) == 4
    assert "job-boards.greenhouse.io" in {e["source"] for e in entries}


def test_unknown_non_domain_source_is_skipped():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    sources = ["ashby", "greenhouse", "lever", "workday", "totallymadeup"]
    entries = dorks.compose_queries([p], None, sources)
    assert len(entries) == 4
    assert {e["source"] for e in entries} == set(dorks.DEFAULT_BOARD_DOMAINS)


def test_none_sources_yields_four_defaults():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    entries = dorks.compose_queries([p], None, None)
    assert len(entries) == len(dorks.DEFAULT_BOARD_DOMAINS) == 4
    sources = {e["source"] for e in entries}
    assert sources == set(dorks.DEFAULT_BOARD_DOMAINS)


def test_empty_list_sources_yields_no_queries():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    assert dorks.compose_queries([p], None, []) == []


def test_defaults_present_even_when_operator_configured_boards():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    sources_in = ["ashby", "greenhouse", "lever", "workday", "linkedin"]
    entries = dorks.compose_queries([p], None, sources_in)
    sources = {e["source"] for e in entries}
    assert sources.issuperset(set(dorks.DEFAULT_BOARD_DOMAINS))
    assert "linkedin.com/jobs" in sources


def test_configuring_a_default_board_explicitly_does_not_duplicate_it():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    entries = dorks.compose_queries([p], None, ["ashby"])
    ashby_entries = [e for e in entries if e["source"] == "jobs.ashbyhq.com"]
    assert len(ashby_entries) == 1


def test_rejected_role_types_render_as_negatives():
    p = JobProfile(
        name="p",
        enabled=True,
        keywords=["backend"],
        rejected_role_types=["contract", "unpaid internship"],
    )
    q = dorks.compose_queries([p], None, ["ashby"])[0]["query"]
    assert '-"contract"' in q
    assert '-"unpaid internship"' in q


def test_remote_model_remote_adds_or_group_to_query_and_url():
    p = JobProfile(name="p", enabled=True, keywords=["backend"], remote_model="remote")
    entry = dorks.compose_queries([p], "none", ["ashby"])[0]
    expected_query = 'site:jobs.ashbyhq.com (remote OR "fully remote" OR "work from home") backend'
    assert entry["query"] == expected_query
    assert unquote_plus(entry["url"].split("q=")[1]) == expected_query


def test_remote_model_hybrid_adds_remote_or_hybrid_group():
    p = JobProfile(name="p", enabled=True, keywords=["backend"], remote_model="hybrid")
    q = dorks.compose_queries([p], "none", ["ashby"])[0]["query"]
    assert q == "site:jobs.ashbyhq.com (remote OR hybrid) backend"


def test_remote_model_on_site_leaves_query_unchanged():
    p = JobProfile(name="p", enabled=True, keywords=["backend"], remote_model="on_site")
    q = dorks.compose_queries([p], "none", ["ashby"])[0]["query"]
    assert q == "site:jobs.ashbyhq.com backend"


def test_remote_model_none_leaves_query_unchanged():
    p = JobProfile(name="p", enabled=True, keywords=["backend"], remote_model=None)
    q = dorks.compose_queries([p], "none", ["ashby"])[0]["query"]
    assert q == "site:jobs.ashbyhq.com backend"


def test_disabled_profile_produces_nothing():
    p = JobProfile(name="p", enabled=False, keywords=["backend"])
    assert dorks.compose_queries([p]) == []


def test_empty_keywords_produces_nothing():
    p = JobProfile(name="p", enabled=True, keywords=[])
    assert dorks.compose_queries([p]) == []


def test_url_is_percent_encoded_and_carries_recency_in_query():
    p = JobProfile(name="p", enabled=True, keywords=["platform engineer"])
    entry = dorks.compose_queries([p], "d", ["ashby"], today=TODAY)[0]
    assert "%22platform+engineer%22" in entry["url"] or "%22platform%20engineer%22" in entry["url"]
    assert "tbs=" not in entry["url"]
    assert entry["query"].endswith(" after:2026-03-09")
    assert unquote_plus(entry["url"].split("q=")[1]) == entry["query"]
    assert parse_qs(urlparse(entry["url"]).query) == {"q": [entry["query"]]}


def test_all_queries_are_returned_uncapped():
    profiles = [
        JobProfile(name=f"p{i}", enabled=True, keywords=[f"backend{i}"])
        for i in range(10)
    ]
    entries = dorks.compose_queries(profiles)
    assert len(entries) == 40  # 10 profiles * 4 default sources


def test_budget_is_shared_round_robin_so_no_profile_is_starved():
    """Queries interleave round-robin, so the first round covers every profile."""
    boards = ["ashby", "greenhouse", "lever", "linkedin", "wellfound", "indeed"]
    profiles = [
        JobProfile(name=f"p{i}", enabled=True, keywords=[f"backend{i}"])
        for i in range(6)
    ]
    entries = dorks.compose_queries(profiles, None, boards)

    expected = sum(len(dorks.compose_profile_queries(p, None, boards)) for p in profiles)
    assert len(entries) == expected
    assert {e["profile"] for e in entries[:6]} == {p.name for p in profiles}


def test_disabled_and_keywordless_profiles_are_excluded_before_sharing_the_budget():
    p1 = JobProfile(name="active", enabled=True, keywords=["backend"])
    p2 = JobProfile(name="disabled", enabled=False, keywords=["backend"])
    p3 = JobProfile(name="no-keywords", enabled=True, keywords=[])
    entries = dorks.compose_queries([p1, p2, p3], None, ["ashby"])
    assert {e["profile"] for e in entries} == {"active"}


# ---------------------------------------------------------------------------
# Posting freshness window
# ---------------------------------------------------------------------------

TODAY = date(2026, 3, 10)


def _entry(recency):
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    return dorks.compose_queries([p], recency, ["ashby"], today=TODAY)[0]


def test_unset_recency_defaults_to_the_past_24_hours():
    assert _entry(None)["query"].endswith(" after:2026-03-09")
    assert "after:2026-03-03" not in _entry(None)["query"]


def test_none_recency_adds_no_operator():
    entry = _entry("none")
    assert "after:" not in entry["query"]
    assert "after" not in entry["url"]


@pytest.mark.parametrize(
    "letter,expected",
    [("d", "2026-03-09"), ("w", "2026-03-03"), ("m", "2026-02-08"), ("y", "2025-03-10")],
)
def test_each_recency_letter_renders_its_after_date(letter, expected):
    entry = _entry(letter)
    assert entry["query"].endswith(f" after:{expected}")
    assert "tbs=" not in entry["url"]


@pytest.mark.parametrize("value", ["bogus", "h"])
def test_invalid_or_legacy_recency_falls_back_to_default(value):
    assert _entry(value)["query"].endswith(" after:2026-03-09")


def test_recency_operator_values():
    assert dorks.recency_operator("d", TODAY) == "after:2026-03-09"
    assert dorks.recency_operator("none", TODAY) == ""
    assert dorks.recency_operator("y", TODAY) == "after:2025-03-10"
    assert dorks.recency_operator(None, TODAY) == "after:2026-03-09"
    assert dorks.recency_operator("x", TODAY) == "after:2026-03-09"
    assert dorks.recency_operator("h", TODAY) == "after:2026-03-09"


def test_recency_operator_defaults_to_utc_today(monkeypatch):
    from datetime import datetime, timezone

    seen_tz = []

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            seen_tz.append(tz)
            return datetime(2026, 3, 10, 23, 30, tzinfo=timezone.utc)

    monkeypatch.setattr(dorks, "datetime", FrozenDatetime)
    assert dorks.recency_operator("w") == "after:2026-03-03"
    assert seen_tz == [timezone.utc]


def test_recency_applies_to_every_composed_query_not_just_the_first():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    entries = dorks.compose_queries([p], "w", today=TODAY)
    assert len(entries) == len(dorks.DEFAULT_BOARD_DOMAINS)
    assert all(e["query"].endswith(" after:2026-03-03") for e in entries)
    assert all("tbs=" not in e["url"] for e in entries)
    assert all(unquote_plus(e["url"].split("q=")[1]) == e["query"] for e in entries)


def test_duplicate_urls_merge_profiles_into_a_profiles_list():
    p1 = JobProfile(name="a", enabled=True, keywords=["backend"])
    p2 = JobProfile(name="b", enabled=True, keywords=["backend"])
    entries = dorks.compose_queries([p1, p2], "d", ["ashby"])
    assert len(entries) == 1
    assert entries[0]["profile"] == "a"
    assert entries[0]["profiles"] == ["a", "b"]


def test_window_is_carried_in_the_query_text():
    """Recency is an after: operator in the query text, so WebSearch honours it."""
    assert _entry("w")["query"] == "site:jobs.ashbyhq.com backend after:2026-03-03"
    assert _entry("none")["query"] == "site:jobs.ashbyhq.com backend"


# ---------------------------------------------------------------------------
# Board mode: direct boards are excluded from dorks, resolve_domain normalises
# hosts, compose_direct_boards composes their on-site search payload.
# ---------------------------------------------------------------------------


def test_direct_mode_board_emits_no_dork():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    defaults = [JobBoard(source=s, mode="dork") for s in ["ashby", "greenhouse", "lever", "workday"]]
    direct_board = JobBoard(source="custom.example.com", mode="direct")
    entries = dorks.compose_queries([p], None, defaults + [direct_board])
    # Only the four always-searched defaults; no entry for the direct board.
    assert len(entries) == 4
    assert "custom.example.com" not in {e["source"] for e in entries}


def test_disabled_default_board_emits_no_dork():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    boards = [
        JobBoard(source="ashby", mode="dork", enabled=False),
        JobBoard(source="greenhouse", mode="dork"),
        JobBoard(source="lever", mode="dork"),
        JobBoard(source="workday", mode="dork"),
    ]
    entries = dorks.compose_queries([p], None, boards)
    assert len(entries) == 3
    assert "jobs.ashbyhq.com" not in {e["source"] for e in entries}


def test_dork_mode_board_still_emits_a_dork():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    dork_board = JobBoard(source="custom.example.com", mode="dork")
    entries = dorks.compose_queries([p], None, [dork_board])
    assert "custom.example.com" in {e["source"] for e in entries}


def test_resolve_domain_normalises_scheme_path_query_and_www():
    assert boards_module.resolve_domain("https://www.wearedevelopers.com/jobs?country=DE") == (
        "wearedevelopers.com"
    )
    assert boards_module.resolve_domain("http://boards.example.io/careers/") == "boards.example.io"
    assert boards_module.resolve_domain("careers.acme.com") == "careers.acme.com"


def test_resolve_domain_of_unparseable_source_is_none():
    assert boards_module.resolve_domain("not-a-domain") is None


def test_two_sources_normalising_to_the_same_host_dedupe_to_one_query():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    a = JobBoard(source="https://www.custom-board.io/jobs", mode="dork")
    b = JobBoard(source="custom-board.io", mode="dork")
    entries = dorks.compose_queries([p], None, [a, b])
    matching = [e for e in entries if e["source"] == "custom-board.io"]
    assert len(matching) == 1


def test_compose_direct_boards_shape():
    p1 = JobProfile(
        name="active",
        enabled=True,
        keywords=["backend"],
        locations=["Berlin"],
        rejected_role_types=["contract"],
        remote_model="remote",
    )
    p2 = JobProfile(name="disabled", enabled=False, keywords=["frontend"])
    p3 = JobProfile(name="no-keywords", enabled=True, keywords=[])
    direct_board = JobBoard(
        source="https://boards.acme.io/careers",
        signin_url="https://boards.acme.io/login",
        mode="direct",
        search_url="https://boards.acme.io/search?q={keywords}",
    )
    dork_board = JobBoard(source="ashby", mode="dork")

    direct_board.posting_url_pattern = "https://boards.acme.io/jobs/*"

    entries = dorks.compose_direct_boards([p1, p2, p3], [direct_board, dork_board])

    assert len(entries) == 1
    entry = entries[0]
    # The URL is verbatim, never normalised to a bare host.
    assert entry["url"] == "https://boards.acme.io/careers"
    assert entry["signin_url"] == "https://boards.acme.io/login"
    assert entry["search_url"] == "https://boards.acme.io/search?q={keywords}"
    assert entry["posting_url_pattern"] == "https://boards.acme.io/jobs/*"
    assert entry["profiles"] == [
        {
            "profile": "active",
            "keywords": ["backend"],
            "locations": ["Berlin"],
            "rejected_role_types": ["contract"],
            "remote_model": "remote",
        }
    ]


def test_compose_direct_boards_carries_none_remote_model_through():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    direct_board = JobBoard(source="https://boards.acme.io/careers", mode="direct")
    entries = dorks.compose_direct_boards([p], [direct_board])
    assert entries[0]["profiles"][0]["remote_model"] is None


def test_compose_direct_boards_empty_when_no_direct_boards():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    assert dorks.compose_direct_boards([p], [JobBoard(source="ashby", mode="dork")]) == []
    assert dorks.compose_direct_boards([p], None) == []


# ---------------------------------------------------------------------------
# Google's ~32-word query limit: titles drive the dork, chunked to fit.
# ---------------------------------------------------------------------------


def _big_profile(prefix="Skill"):
    keywords = [f"{prefix}{i} Engineer" for i in range(80)]
    return JobProfile(
        name="big",
        enabled=True,
        keywords=keywords,
        locations=["Berlin", "Remote"],
        remote_model="remote",
        rejected_role_types=["contract", "unpaid internship", "internship", "temporary"],
    )


def test_every_composed_query_fits_googles_word_limit():
    p = _big_profile()
    entries = dorks.compose_profile_queries(p, None, ["ashby"])
    assert entries
    assert all(dorks._word_count(e["query"]) <= dorks.MAX_QUERY_WORDS for e in entries)


def test_location_and_remote_groups_present_in_every_query():
    p = _big_profile()
    entries = dorks.compose_profile_queries(p, None, ["ashby"])
    assert all("(Berlin OR Remote)" in e["query"] for e in entries)
    assert all('"fully remote"' in e["query"] for e in entries)


def test_title_keywords_overrides_keywords():
    p = JobProfile(name="p", enabled=True, keywords=["Python"], title_keywords=["Data Engineer"])
    q = dorks.compose_queries([p], None, ["ashby"])[0]["query"]
    assert "Data Engineer" in q
    assert "Python" not in q


def test_fallback_detects_titles_among_keywords_not_bare_skills():
    p = JobProfile(name="p", enabled=True, keywords=["Python", "Data Engineer"])
    q = dorks.compose_queries([p], None, ["ashby"])[0]["query"]
    assert "Data Engineer" in q
    assert "Python" not in q


def test_fallback_to_raw_keywords_when_nothing_matches_title_nouns():
    p = JobProfile(name="p", enabled=True, keywords=["Python", "SQL"])
    q = dorks.compose_queries([p], None, ["ashby"])[0]["query"]
    assert "Python" in q
    assert "SQL" in q


def test_chunks_ordered_chunk_major_across_domains():
    p = _big_profile()
    entries = dorks.compose_profile_queries(p, None, ["ashby", "greenhouse"])
    sources_seen = [e["source"] for e in entries]
    # 5 default+extra domains repeat once per chunk; chunk-major means the
    # first block covers every domain before any domain repeats.
    domain_count = len(dorks._resolve_sources(["ashby", "greenhouse"]))
    first_block = sources_seen[:domain_count]
    assert len(set(first_block)) == domain_count


def _edge_locations():
    return [f"City{i}" for i in range(13)] + ["New City"]


def test_query_exactly_at_budget_with_after_token_stays_within_limit():
    p = JobProfile(
        name="p", enabled=True, keywords=["Backend Engineer"], locations=_edge_locations()
    )
    entries = dorks.compose_profile_queries(p, "w", ["ashby"], today=TODAY)
    assert len(entries) == 1
    assert entries[0]["query"].endswith(" after:2026-03-03")
    assert dorks._word_count(entries[0]["query"]) == dorks.MAX_QUERY_WORDS


def test_negatives_dropped_rather_than_exceeding_budget():
    p = JobProfile(
        name="p",
        enabled=True,
        keywords=["Backend Engineer"],
        # 13 one-word + 1 two-word location -> 28-word OR-group; with site:,
        # the after: token and the 2-word title that is exactly
        # MAX_QUERY_WORDS, leaving no room for any negative.
        locations=_edge_locations(),
        rejected_role_types=["contract", "unpaid internship", "temporary work"],
    )
    entries = dorks.compose_profile_queries(p, None, ["ashby"], today=TODAY)
    assert all(dorks._word_count(e["query"]) == dorks.MAX_QUERY_WORDS for e in entries)
    assert all(dorks._word_count(e["query"]) <= dorks.MAX_QUERY_WORDS for e in entries)
    assert all('-"contract"' not in e["query"] for e in entries)


def test_padded_titles_are_stripped_so_budget_holds():
    p = JobProfile(
        name="p",
        enabled=True,
        keywords=["x"],
        title_keywords=[" Backend Engineer ", "  "],
        locations=_edge_locations(),
    )
    entries = dorks.compose_profile_queries(p, None, ["ashby"], today=TODAY)
    assert entries
    assert all(dorks._word_count(e["query"]) <= dorks.MAX_QUERY_WORDS for e in entries)
    assert all('"Backend Engineer"' in e["query"] for e in entries)


def test_all_chunked_queries_returned_and_interleaved():
    profiles = [_big_profile(f"S{i}x") for i in range(3)]
    for i, p in enumerate(profiles):
        p.name = f"big{i}"
    entries = dorks.compose_queries(profiles, None, ["ashby"])
    expected = sum(len(dorks.compose_profile_queries(p, None, ["ashby"])) for p in profiles)
    assert len(entries) == expected
    assert [e["profile"] for e in entries[:3]] == ["big0", "big1", "big2"]


def test_identical_profiles_dedupe_to_first_profile():
    a = JobProfile(name="first", enabled=True, keywords=["backend"])
    b = JobProfile(name="second", enabled=True, keywords=["backend"])
    entries = dorks.compose_queries([a, b], None, ["ashby"])
    assert len(entries) == 1
    assert entries[0]["profile"] == "first"


def test_profiles_differing_only_in_locations_are_both_kept():
    a = JobProfile(name="a", enabled=True, keywords=["backend"], locations=["Berlin"])
    b = JobProfile(name="b", enabled=True, keywords=["backend"], locations=["Paris"])
    entries = dorks.compose_queries([a, b], None, ["ashby"])
    assert [e["profile"] for e in entries] == ["a", "b"]


def test_dedupe_preserves_surviving_order():
    a = JobProfile(name="a", enabled=True, keywords=["backend"])
    b = JobProfile(name="b", enabled=True, keywords=["backend"])
    c = JobProfile(name="c", enabled=True, keywords=["frontend"])
    entries = dorks.compose_queries([a, b, c], None, ["ashby", "greenhouse"])
    assert [(e["profile"], e["source"]) for e in entries] == [
        ("a", "jobs.ashbyhq.com"),
        ("c", "jobs.ashbyhq.com"),
        ("a", "job-boards.greenhouse.io"),
        ("c", "job-boards.greenhouse.io"),
    ]
