"""Dork-query composer: query shape, source resolution, filtering, caps."""

from urllib.parse import unquote_plus

from agentconfig import boards as boards_module
from agentconfig import dorks
from agentconfig.store import JobBoard, JobProfile


def test_multi_word_keyword_is_quoted_single_word_is_not():
    p = JobProfile(name="p", enabled=True, keywords=["platform engineer", "SRE"])
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
    entries = dorks.compose_queries([p], None, ["custom.example.com"])
    # 4 defaults + the custom domain.
    assert len(entries) == 5
    custom = next(e for e in entries if e["source"] == "custom.example.com")
    assert custom["query"].startswith("site:custom.example.com")


def test_known_source_name_maps_to_domain():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    # "greenhouse" is already one of the four defaults, so no duplicate entry.
    entries = dorks.compose_queries([p], None, ["greenhouse"])
    assert len(entries) == 4
    assert "job-boards.greenhouse.io" in {e["source"] for e in entries}


def test_unknown_non_domain_source_is_skipped():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    entries = dorks.compose_queries([p], None, ["totallymadeup"])
    assert len(entries) == 4
    assert {e["source"] for e in entries} == set(dorks.DEFAULT_BOARD_DOMAINS)


def test_defaults_present_when_no_boards_configured():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    entries = dorks.compose_queries([p], None, [])
    assert len(entries) == len(dorks.DEFAULT_BOARD_DOMAINS) == 4
    sources = {e["source"] for e in entries}
    assert sources == set(dorks.DEFAULT_BOARD_DOMAINS)


def test_defaults_present_even_when_operator_configured_boards():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    entries = dorks.compose_queries([p], None, ["linkedin"])
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


def test_disabled_profile_produces_nothing():
    p = JobProfile(name="p", enabled=False, keywords=["backend"])
    assert dorks.compose_queries([p]) == []


def test_empty_keywords_produces_nothing():
    p = JobProfile(name="p", enabled=True, keywords=[])
    assert dorks.compose_queries([p]) == []


def test_url_is_percent_encoded_and_carries_recency_param():
    p = JobProfile(name="p", enabled=True, keywords=["platform engineer"])
    entry = dorks.compose_queries([p], None, ["ashby"])[0]
    assert "%22platform+engineer%22" in entry["url"] or "%22platform%20engineer%22" in entry["url"]
    assert entry["url"].endswith("&tbs=qdr:w")
    assert unquote_plus(entry["url"].split("q=")[1].split("&tbs=")[0]) == entry["query"]


def test_total_is_truncated_at_max_queries():
    profiles = [
        JobProfile(name=f"p{i}", enabled=True, keywords=["backend"])
        for i in range(10)
    ]
    entries = dorks.compose_queries(profiles)
    assert len(entries) <= dorks.MAX_QUERIES
    assert len(entries) == dorks.MAX_QUERIES  # 10 profiles * 4 default sources = 40 > 24


# ---------------------------------------------------------------------------
# Posting freshness window
# ---------------------------------------------------------------------------

def _url(days):
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    return dorks.compose_queries([p], days, ["ashby"])[0]["url"]


def test_unset_window_keeps_the_historical_past_week_filter():
    """None must not silently widen discovery on an existing config: these URLs
    have always carried qdr:w, and introducing the setting changes nothing."""
    assert "&tbs=qdr:w" in _url(None)


def test_zero_days_disables_the_recency_filter_entirely():
    """0 disables the window, mirroring how 0 disables a cooldown window."""
    assert "tbs=" not in _url(0)


def test_a_window_renders_googles_n_days_form():
    assert "&tbs=qdr:d3" in _url(3)
    assert "&tbs=qdr:d30" in _url(30)


def test_negative_window_is_treated_as_disabled_not_as_a_malformed_url():
    """The API validator rejects negatives, but the composer is called with
    stored config too — a hand-edited -1 must not emit tbs=qdr:d-1."""
    assert "tbs=" not in _url(-1)


def test_recency_param_values():
    assert dorks.recency_param(None) == "qdr:w"
    assert dorks.recency_param(0) == ""
    assert dorks.recency_param(7) == "qdr:d7"


def test_window_applies_to_every_composed_query_not_just_the_first():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    entries = dorks.compose_queries([p], 5)
    assert len(entries) == len(dorks.DEFAULT_BOARD_DOMAINS)
    assert all("&tbs=qdr:d5" in e["url"] for e in entries)


def test_window_does_not_alter_the_query_string_itself():
    """The recency filter is a URL parameter; the query text the agent feeds to
    WebSearch must be unchanged, since WebSearch ignores tbs anyway."""
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    assert (
        dorks.compose_queries([p], 5, ["ashby"])[0]["query"]
        == dorks.compose_queries([p], None, ["ashby"])[0]["query"]
    )


# ---------------------------------------------------------------------------
# Board mode: direct boards are excluded from dorks, resolve_domain normalises
# hosts, compose_direct_boards composes their on-site search payload.
# ---------------------------------------------------------------------------


def test_direct_mode_board_emits_no_dork():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    direct_board = JobBoard(source="custom.example.com", mode="direct")
    entries = dorks.compose_queries([p], None, [direct_board])
    # Only the four always-searched defaults; no entry for the direct board.
    assert len(entries) == 4
    assert "custom.example.com" not in {e["source"] for e in entries}


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
    )
    p2 = JobProfile(name="disabled", enabled=False, keywords=["frontend"])
    p3 = JobProfile(name="no-keywords", enabled=True, keywords=[])
    direct_board = JobBoard(
        source="https://boards.acme.io/careers",
        signin_url="https://boards.acme.io/login",
        mode="direct",
    )
    dork_board = JobBoard(source="ashby", mode="dork")

    entries = dorks.compose_direct_boards([p1, p2, p3], [direct_board, dork_board])

    assert len(entries) == 1
    entry = entries[0]
    # The URL is verbatim, never normalised to a bare host.
    assert entry["url"] == "https://boards.acme.io/careers"
    assert entry["signin_url"] == "https://boards.acme.io/login"
    assert entry["profiles"] == [
        {
            "profile": "active",
            "keywords": ["backend"],
            "locations": ["Berlin"],
            "rejected_role_types": ["contract"],
        }
    ]


def test_compose_direct_boards_empty_when_no_direct_boards():
    p = JobProfile(name="p", enabled=True, keywords=["backend"])
    assert dorks.compose_direct_boards([p], [JobBoard(source="ashby", mode="dork")]) == []
    assert dorks.compose_direct_boards([p], None) == []
