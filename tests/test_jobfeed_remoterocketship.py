"""jobfeeds/remoterocketship.py: profile→filters mapping, response parsing, failure handling."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from agentconfig.store import JobProfile
from jobfeeds import remoterocketship as rr

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)


def _profile(**kwargs) -> JobProfile:
    base = {"name": "p", "enabled": True, "keywords": ["platform engineer"]}
    base.update(kwargs)
    return JobProfile(**base)


def _opening(**kwargs) -> dict:
    base = {
        "id": 1,
        "roleTitle": "Senior Platform Engineer",
        "url": "https://acme.example/jobs/1",
        "created_at": "2026-08-26T09:00:00.000Z",
        "salaryRange": "$120k-$150k",
        "employmentType": "full-time",
        "company": {"name": "Acme"},
    }
    base.update(kwargs)
    return base


# Captured once at import, before any test patches httpx.Client. Reading
# httpx.Client inside the factory would, on a second install() in the same
# test, subclass the already-patched class and inherit the FIRST handler.
_REAL_CLIENT = httpx.Client


def _client(handler):
    """Point httpx.Client at a MockTransport for the duration of a test."""

    class Patched(_REAL_CLIENT):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kw)

    return Patched


@pytest.fixture()
def mock_http(monkeypatch):
    def install(handler):
        monkeypatch.setattr(httpx, "Client", _client(handler))

    return install


# --- filters mapping -------------------------------------------------------


def test_keywords_go_to_keyword_filters_not_the_closed_title_enum():
    filters = rr.filters_for_profile(_profile(keywords=["platform engineer", "SRE"]))
    assert filters["keywordFilters"] == ["platform engineer", "SRE"]
    assert "jobTitleFilters" not in filters


def test_rejected_role_types_become_excluded_keywords():
    filters = rr.filters_for_profile(_profile(rejected_role_types=["intern", "sales"]))
    assert filters["excludedKeywordFilters"] == ["intern", "sales"]


def test_salary_floor_keeps_postings_that_state_no_salary():
    """A posting with no stated salary must survive the floor: the agent screens
    salary from the posting text, and dropping it here would hide roles it could
    still negotiate."""
    filters = rr.filters_for_profile(_profile(salary_floor=120000))
    assert filters["minSalaryFilter"] == 120000
    assert filters["showJobsWithoutSalaryWithMinSalaryFilter"] is True


def test_zero_and_missing_salary_floor_send_no_salary_filter():
    assert "minSalaryFilter" not in rr.filters_for_profile(_profile(salary_floor=0))
    assert "minSalaryFilter" not in rr.filters_for_profile(_profile(salary_floor=None))


def test_remote_model_maps_to_visibility_flags():
    remote = rr.filters_for_profile(_profile(remote_model="remote"))
    assert (remote["showRemoteJobs"], remote["showHybridJobs"], remote["showOnsiteJobs"]) == (True, False, False)

    hybrid = rr.filters_for_profile(_profile(remote_model="Hybrid"))
    assert (hybrid["showRemoteJobs"], hybrid["showHybridJobs"]) == (True, True)

    onsite = rr.filters_for_profile(_profile(remote_model="on-site"))
    assert (onsite["showRemoteJobs"], onsite["showOnsiteJobs"]) == (False, True)

    # An unset or unrecognised remote_model falls back to remote-only rather
    # than to "everything" — this board is a remote job board.
    unset = rr.filters_for_profile(_profile(remote_model=None))
    assert (unset["showRemoteJobs"], unset["showOnsiteJobs"]) == (True, False)


def test_items_per_page_never_exceeds_the_boards_ceiling():
    assert rr.filters_for_profile(_profile())["itemsPerPage"] == 50


def test_filters_ask_for_newest_first_and_invent_no_date_filter():
    """The API documents no date filter, so the freshness window cannot be
    pushed into the request — an invented key would be silently ignored and the
    window lost. Newest-first ordering is what makes the client-side window
    useful on a capped page."""
    filters = rr.filters_for_profile(_profile())
    assert filters["sortBy"] == "DateAdded"
    assert "postedAfter" not in filters
    assert "maxPostingAgeDays" not in filters


# --- fetching --------------------------------------------------------------


def test_the_endpoint_url_carries_the_trailing_slash_the_host_requires():
    """Without it the host answers every POST with a 308 to the slashed form
    and the request never reaches the handler. The published docs give the
    un-slashed path, so this is easy to "correct" back into a total outage."""
    assert rr.API_URL.endswith("/jobs/")


def test_a_redirect_is_followed_rather_than_reported_as_a_failure(mock_http):
    """Belt to the trailing slash's braces: if the host moves the path again,
    the feed should follow it instead of failing every request. A 308 preserves
    the method and body, so the POST survives the hop."""
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if not request.url.path.endswith("/moved/"):
            return httpx.Response(308, headers={"Location": "/api/openclaw/moved/"})
        return httpx.Response(200, json={"jobOpenings": [_opening()]})

    mock_http(handler)
    result = rr.fetch_postings([_profile()], "k", now=NOW)

    assert len(seen) == 2
    assert result.error == ""
    assert len(result.postings) == 1


def test_check_key_follows_a_redirect_too(mock_http):
    """The Test button must not report a healthy key as broken."""
    def handler(request):
        if not request.url.path.endswith("/moved/"):
            return httpx.Response(308, headers={"Location": "/api/openclaw/moved/"})
        return httpx.Response(200, json={"jobOpenings": []})

    mock_http(handler)
    ok, _ = rr.check_key("k")
    assert ok


def test_no_key_returns_empty_without_calling_out(mock_http):
    def handler(request):  # pragma: no cover — must never run
        raise AssertionError("fetch_postings called the API without a key")

    mock_http(handler)
    result = rr.fetch_postings([_profile()], "", now=NOW)
    assert result.postings == []
    assert result.error == ""


def test_successful_fetch_maps_postings(mock_http):
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"jobOpenings": [_opening()], "totalCount": 1})

    mock_http(handler)
    result = rr.fetch_postings([_profile()], "rr_secret", now=NOW)

    assert captured["auth"] == "Bearer rr_secret"
    assert result.error == ""
    assert len(result.postings) == 1
    posting = result.postings[0]
    assert posting.title == "Senior Platform Engineer"
    assert posting.company == "Acme"
    assert posting.url == "https://acme.example/jobs/1"
    assert posting.salary_range == "$120k-$150k"
    assert posting.profile == "p"
    assert posting.source == "remoterocketship"


def test_posting_without_a_url_is_dropped(mock_http):
    """An agent cannot open, screen, or apply to a posting with no URL — leaving
    it in the prompt only invites a guess at where it lives."""
    mock_http(lambda r: httpx.Response(200, json={"jobOpenings": [_opening(url=""), _opening()]}))
    result = rr.fetch_postings([_profile()], "k", now=NOW)
    assert [p.url for p in result.postings] == ["https://acme.example/jobs/1"]


def test_postings_are_deduplicated_by_url_across_profiles(mock_http):
    mock_http(lambda r: httpx.Response(200, json={"jobOpenings": [_opening()]}))
    result = rr.fetch_postings(
        [_profile(name="a"), _profile(name="b")], "k", now=NOW
    )
    assert len(result.postings) == 1
    assert result.postings[0].profile == "a"


def test_disabled_and_keywordless_profiles_are_skipped(mock_http):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"jobOpenings": []})

    mock_http(handler)
    rr.fetch_postings(
        [_profile(name="off", enabled=False), _profile(name="bare", keywords=[]), _profile(name="ok")],
        "k",
        now=NOW,
    )
    assert len(calls) == 1


def test_freshness_window_drops_older_postings_but_keeps_undated_ones(mock_http):
    old = (NOW - timedelta(days=40)).isoformat()
    mock_http(
        lambda r: httpx.Response(
            200,
            json={
                "jobOpenings": [
                    _opening(url="https://a.example/1", created_at=old),
                    _opening(url="https://b.example/2", created_at=""),
                    _opening(url="https://c.example/3"),
                ]
            },
        )
    )
    result = rr.fetch_postings([_profile()], "k", max_posting_age_days=7, now=NOW)
    urls = [p.url for p in result.postings]
    # The old one goes; the undated one stays, matching the agent's own rule
    # that an unstated date is never a rejection reason.
    assert urls == ["https://b.example/2", "https://c.example/3"]


def test_unset_or_zero_age_window_filters_nothing(mock_http):
    old = (NOW - timedelta(days=400)).isoformat()
    mock_http(lambda r: httpx.Response(200, json={"jobOpenings": [_opening(created_at=old)]}))
    for window in (None, 0, 999, True):
        result = rr.fetch_postings([_profile()], "k", max_posting_age_days=window, now=NOW)
        assert len(result.postings) == 1, window


def test_postings_are_capped(mock_http):
    openings = [_opening(url=f"https://acme.example/jobs/{i}") for i in range(200)]
    mock_http(lambda r: httpx.Response(200, json={"jobOpenings": openings}))
    result = rr.fetch_postings([_profile()], "k", now=NOW)
    assert len(result.postings) == rr.MAX_POSTINGS


def test_request_count_is_capped_across_profiles(mock_http):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"jobOpenings": []})

    mock_http(handler)
    rr.fetch_postings([_profile(name=f"p{i}") for i in range(30)], "k", now=NOW)
    assert len(calls) == rr.MAX_REQUESTS


def test_a_slow_feed_stops_at_the_budget_and_keeps_what_it_got(mock_http, monkeypatch):
    """The agent fetches the feed inside its config request, under a fixed
    socket timeout. Per-request timeouts do not bound the total, and a config
    fetch that times out aborts the run instead of costing only the feed."""
    clock = {"t": 0.0}
    monkeypatch.setattr(rr.time, "monotonic", lambda: clock["t"])
    calls = []

    def handler(request):
        calls.append(1)
        clock["t"] += 5.0
        return httpx.Response(200, json={"jobOpenings": [_opening(url=f"https://a.example/{len(calls)}")]})

    mock_http(handler)
    result = rr.fetch_postings([_profile(name=f"p{i}") for i in range(8)], "k", now=NOW)

    assert len(calls) == 4  # 0s, 5s, 10s, 15s — the 5th would start at the 20s budget
    assert len(result.postings) == 4  # what was collected is kept, not discarded
    assert "too slow" in result.error


def test_a_request_never_outlives_the_remaining_budget(mock_http, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(rr.time, "monotonic", lambda: clock["t"])
    timeouts = []

    def handler(request):
        timeouts.append(request.extensions["timeout"]["read"])
        clock["t"] += 16.0
        return httpx.Response(200, json={"jobOpenings": []})

    mock_http(handler)
    rr.fetch_postings([_profile(name="a"), _profile(name="b")], "k", now=NOW)
    assert timeouts[0] == rr.TIMEOUT_SECONDS
    # 16s spent, 4s of budget left — the second request must not be allowed 8s.
    assert timeouts[1] == pytest.approx(4.0)


def test_the_budget_is_below_the_agents_config_fetch_timeout():
    """The two numbers are a contract across two languages. agent-config.js
    allows 30s for job_config; the budget must leave room for the rest of the
    config route on top of it."""
    assert rr.BUDGET_SECONDS < 30
    assert rr.TIMEOUT_SECONDS <= rr.BUDGET_SECONDS


def test_an_explicit_deadline_overrides_the_default_budget(mock_http, monkeypatch):
    """A caller fanning this fetch out alongside another source (see
    api/routes.py's _fetch_feed_postings) passes its own shared deadline; it
    must be honored instead of a fresh BUDGET_SECONDS window."""
    monkeypatch.setattr(rr.time, "monotonic", lambda: 0.0)
    timeouts = []

    def handler(request):
        timeouts.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, json={"jobOpenings": []})

    mock_http(handler)
    # A deadline 3s out — far tighter than the module's own 20s BUDGET_SECONDS
    # — must be what actually governs the request's timeout.
    rr.fetch_postings([_profile(name="a")], "k", now=NOW, deadline=3.0)
    assert timeouts[0] == pytest.approx(3.0)


@pytest.mark.parametrize(
    "status,message,expected",
    [
        (401, "Invalid API key", "Invalid API key"),
        (403, "Active subscription required", "Active subscription required"),
        (429, "Daily request limit reached", "Daily request limit reached"),
    ],
)
def test_account_level_failures_stop_after_one_request(mock_http, status, message, expected):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"message": message})

    mock_http(handler)
    result = rr.fetch_postings([_profile(name="a"), _profile(name="b")], "k", now=NOW)
    # A rejected key or an exhausted quota is a fact about the account, not
    # about this profile — retrying burns quota to be told the same thing.
    assert len(calls) == 1
    assert result.error == expected
    assert result.postings == []


def test_transport_failure_is_reported_not_raised(mock_http):
    def handler(request):
        raise httpx.ConnectError("no route to host")

    mock_http(handler)
    result = rr.fetch_postings([_profile()], "k", now=NOW)
    assert result.postings == []
    assert "Could not reach Remote Rocketship" in result.error


def test_unexpected_response_shape_is_reported_not_raised(mock_http):
    mock_http(lambda r: httpx.Response(200, json={"nope": True}))
    result = rr.fetch_postings([_profile()], "k", now=NOW)
    assert result.postings == []
    assert "unexpected response shape" in result.error


def test_a_failing_profile_does_not_discard_a_succeeding_one(mock_http):
    responses = [
        httpx.Response(500, json={"message": "Unable to fetch jobs"}),
        httpx.Response(200, json={"jobOpenings": [_opening()]}),
    ]

    def handler(request):
        return responses.pop(0)

    mock_http(handler)
    result = rr.fetch_postings([_profile(name="a"), _profile(name="b")], "k", now=NOW)
    assert len(result.postings) == 1
    assert result.error == "Unable to fetch jobs"


def test_pagination_accumulates_postings_beyond_one_page(mock_http):
    """Regression: the old code issued exactly one page-1 request per profile
    and could never return more than ITEMS_PER_PAGE postings from one profile.
    A board holding more matching postings than a single page must still all
    come back from one fetch_postings call."""
    first_page = [_opening(url=f"https://acme.example/jobs/{i}") for i in range(rr.ITEMS_PER_PAGE)]
    second_page = [
        _opening(url=f"https://acme.example/jobs/{i}")
        for i in range(rr.ITEMS_PER_PAGE, rr.ITEMS_PER_PAGE + 5)
    ]

    def handler(request):
        page = json.loads(request.content)["filters"]["page"]
        return httpx.Response(200, json={"jobOpenings": first_page if page == 1 else second_page})

    mock_http(handler)
    result = rr.fetch_postings([_profile()], "k", now=NOW)

    assert len(result.postings) == rr.ITEMS_PER_PAGE + 5
    assert len(result.postings) > rr.ITEMS_PER_PAGE


def test_a_short_page_stops_the_pagination_loop(mock_http):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"jobOpenings": [_opening()]})  # 1 < ITEMS_PER_PAGE

    mock_http(handler)
    rr.fetch_postings([_profile()], "k", now=NOW)
    assert len(calls) == 1


def test_max_postings_stops_the_loop_mid_page(mock_http, monkeypatch):
    """MAX_POSTINGS can be reached inside a single page, before that page's own
    last item — pagination must stop right there instead of finishing the page
    or requesting a next one."""
    monkeypatch.setattr(rr, "MAX_POSTINGS", 30)
    calls = []
    openings = [_opening(url=f"https://acme.example/jobs/{i}") for i in range(rr.ITEMS_PER_PAGE)]

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"jobOpenings": openings})

    mock_http(handler)
    result = rr.fetch_postings([_profile()], "k", now=NOW)
    assert len(result.postings) == 30
    assert len(calls) == 1


def test_max_requests_stops_pagination_regardless_of_budget_or_postings(mock_http, monkeypatch):
    """MAX_REQUESTS must cut pagination off on its own: a board with unlimited
    unique postings and a generous MAX_POSTINGS would otherwise paginate until
    the time budget happened to catch it, which is not a bound at all against
    a fast board."""
    monkeypatch.setattr(rr, "MAX_POSTINGS", 10_000)
    calls = []

    def handler(request):
        calls.append(1)
        openings = [
            _opening(url=f"https://acme.example/jobs/{len(calls)}-{i}") for i in range(rr.ITEMS_PER_PAGE)
        ]
        return httpx.Response(200, json={"jobOpenings": openings})

    mock_http(handler)
    result = rr.fetch_postings([_profile()], "k", now=NOW)
    assert len(calls) == rr.MAX_REQUESTS
    assert len(result.postings) == rr.MAX_REQUESTS * rr.ITEMS_PER_PAGE


def test_budget_exhaustion_can_stop_mid_pagination_for_one_profile(mock_http, monkeypatch):
    """Regression: the old one-request-per-profile code had no inner page loop
    for the budget to interrupt. The budget must be able to cut pagination off
    inside a single profile's own pages, not just between profiles."""
    monkeypatch.setattr(rr, "MAX_POSTINGS", 1000)
    clock = {"t": 0.0}
    monkeypatch.setattr(rr.time, "monotonic", lambda: clock["t"])
    calls = []

    def handler(request):
        calls.append(1)
        clock["t"] += 11.0
        openings = [
            _opening(url=f"https://acme.example/jobs/{len(calls)}-{i}") for i in range(rr.ITEMS_PER_PAGE)
        ]
        return httpx.Response(200, json={"jobOpenings": openings})

    mock_http(handler)
    result = rr.fetch_postings([_profile()], "k", now=NOW)

    assert len(calls) == 2  # 0s, 11s — the 3rd would start at 22s, past the 20s budget
    assert len(result.postings) == 2 * rr.ITEMS_PER_PAGE
    # Only one profile ran, so nothing was "skipped" — its OWN later pages
    # were cut off, and the message must say that rather than the multi-
    # profile wording.
    assert result.error == "Remote Rocketship was too slow; later postings were not fetched."


def test_last_profile_reclaims_budget_earlier_empty_profiles_did_not_spend(mock_http):
    """Regression: without reclaiming, _profile_budget_shares(4) caps every
    profile — including the last — at MAX_POSTINGS // 4 (15), even when a/b/c
    matched nothing and left their whole share of the budget unspent. The
    fix recomputes each profile's share from what remains, so profile d can
    still reach the fetch-wide MAX_POSTINGS ceiling."""

    def handler(request):
        filters = json.loads(request.content)["filters"]
        keyword, page = filters["keywordFilters"][0], filters["page"]
        if keyword != "kw-d":
            return httpx.Response(200, json={"jobOpenings": []})
        openings = [_opening(url=f"https://acme.example/d/{page}-{i}") for i in range(rr.ITEMS_PER_PAGE)]
        return httpx.Response(200, json={"jobOpenings": openings})

    mock_http(handler)
    profiles = [
        _profile(name="a", keywords=["kw-a"]),
        _profile(name="b", keywords=["kw-b"]),
        _profile(name="c", keywords=["kw-c"]),
        _profile(name="d", keywords=["kw-d"]),
    ]
    result = rr.fetch_postings(profiles, "k", now=NOW)

    d_postings = [p for p in result.postings if p.profile == "d"]
    assert len(d_postings) == rr.MAX_POSTINGS


def test_budget_exhaustion_with_more_profiles_remaining_reports_profiles_skipped(mock_http, monkeypatch):
    """Regression for defect #4: _BUDGET_MESSAGE_PROFILES_SKIPPED is asserted
    by no other test, so the more_profiles_remain ternary in
    _fetch_profile_pages could have its two branches silently swapped. Three
    profiles: a completes (one short request), then the budget is exhausted
    right as b's own fetch begins — with c still to come, that must report
    the multi-profile "some profiles were skipped" wording, not the
    single-profile "pagination cut short" one."""
    clock = {"t": 0.0}
    monkeypatch.setattr(rr.time, "monotonic", lambda: clock["t"])

    def handler(request):
        clock["t"] += 25.0  # exhausts the 20s budget right after profile a's one request
        return httpx.Response(200, json={"jobOpenings": [_opening()]})

    mock_http(handler)
    result = rr.fetch_postings(
        [_profile(name="a"), _profile(name="b"), _profile(name="c")], "k", now=NOW
    )

    assert result.error == rr._BUDGET_MESSAGE_PROFILES_SKIPPED
    assert len(result.postings) == 1  # profile a's own posting is kept


def test_second_profile_is_still_requested_when_first_could_fill_the_budget_alone(mock_http):
    """Regression: before per-profile budget shares, one profile whose board
    held more than MAX_POSTINGS fresh matches would page until MAX_POSTINGS
    (or MAX_REQUESTS) was hit, and the fetch-wide check in the outer loop
    would then skip every later profile entirely — it would never even be
    requested once."""
    calls_by_keyword = {"kw-a": 0, "kw-b": 0}

    def handler(request):
        filters = json.loads(request.content)["filters"]
        keyword = filters["keywordFilters"][0]
        calls_by_keyword[keyword] += 1
        page = filters["page"]
        # An inexhaustible board: every page, for every profile, comes back
        # full and with URLs nobody has seen yet.
        openings = [
            _opening(url=f"https://acme.example/{keyword}/{page}-{i}") for i in range(rr.ITEMS_PER_PAGE)
        ]
        return httpx.Response(200, json={"jobOpenings": openings})

    mock_http(handler)
    result = rr.fetch_postings(
        [_profile(name="a", keywords=["kw-a"]), _profile(name="b", keywords=["kw-b"])], "k", now=NOW
    )

    assert calls_by_keyword["kw-b"] > 0
    assert any(p.profile == "b" for p in result.postings)


def test_stall_check_is_scoped_to_the_current_profiles_own_pages(mock_http, monkeypatch):
    """Regression: _page_is_stalled used to compare a page against the
    fetch-wide seen_urls, so a profile whose page 1 exactly matched an
    EARLIER profile's results looked "stalled" and never reached its own
    later, genuinely new pages."""
    monkeypatch.setattr(rr, "ITEMS_PER_PAGE", 2)
    monkeypatch.setattr(rr, "MAX_POSTINGS", 1000)
    monkeypatch.setattr(rr, "MAX_REQUESTS", 1000)

    shared = [_opening(url="https://acme.example/shared/0"), _opening(url="https://acme.example/shared/1")]
    profile_b_page2 = [_opening(url="https://acme.example/b/only")]

    def handler(request):
        filters = json.loads(request.content)["filters"]
        keyword, page = filters["keywordFilters"][0], filters["page"]
        if keyword == "kw-a":
            return httpx.Response(200, json={"jobOpenings": shared if page == 1 else []})
        # profile b's page 1 exactly duplicates profile a's page 1; its page 2
        # holds a posting nothing else has returned.
        return httpx.Response(200, json={"jobOpenings": shared if page == 1 else profile_b_page2})

    mock_http(handler)
    result = rr.fetch_postings(
        [_profile(name="a", keywords=["kw-a"]), _profile(name="b", keywords=["kw-b"])], "k", now=NOW
    )

    assert any(p.url == "https://acme.example/b/only" for p in result.postings)


def test_a_board_that_ignores_the_page_param_terminates_instead_of_looping(mock_http):
    """Defensive: if the board's page filter has no effect, page 2 (and every
    page after) returns exactly what page 1 did, and dedupe-by-URL finds
    nothing new. The fetch must stop there rather than loop until a budget or
    request cap happens to intervene."""
    same_page = [_opening(url=f"https://acme.example/jobs/{i}") for i in range(rr.ITEMS_PER_PAGE)]
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"jobOpenings": same_page})

    mock_http(handler)
    result = rr.fetch_postings([_profile()], "k", now=NOW)

    assert len(calls) == 2  # page 1, then one repeat that is detected as stalled
    assert len(result.postings) == rr.ITEMS_PER_PAGE


def test_dedupe_by_url_holds_across_pages(mock_http):
    """A URL repeated on a later page (e.g. a board padding page 2 with some of
    page 1's results) must not be counted twice, while genuinely new URLs on
    that same page still are."""
    page1 = [_opening(url=f"https://acme.example/jobs/{i}") for i in range(rr.ITEMS_PER_PAGE)]
    page2 = [_opening(url="https://acme.example/jobs/0")] + [
        _opening(url=f"https://acme.example/jobs/{i}")
        for i in range(rr.ITEMS_PER_PAGE, rr.ITEMS_PER_PAGE + 3)
    ]

    def handler(request):
        page = json.loads(request.content)["filters"]["page"]
        return httpx.Response(200, json={"jobOpenings": page1 if page == 1 else page2})

    mock_http(handler)
    result = rr.fetch_postings([_profile()], "k", now=NOW)
    assert len(result.postings) == rr.ITEMS_PER_PAGE + 3


def test_the_api_key_never_appears_in_the_result(mock_http):
    mock_http(lambda r: httpx.Response(401, json={"message": "Invalid API key"}))
    result = rr.fetch_postings([_profile()], "rr_super_secret", now=NOW)
    assert "rr_super_secret" not in result.error
    assert "rr_super_secret" not in repr(result)


# --- key check -------------------------------------------------------------


def test_check_key_reports_success_and_failure(mock_http):
    mock_http(lambda r: httpx.Response(200, json={"jobOpenings": []}))
    ok, detail = rr.check_key("k")
    assert ok and detail

    mock_http(lambda r: httpx.Response(403, json={"message": "Active subscription required"}))
    ok, detail = rr.check_key("k")
    assert not ok
    assert detail == "Active subscription required"


def test_check_key_with_no_key_does_not_call_out(mock_http):
    def handler(request):  # pragma: no cover — must never run
        raise AssertionError("check_key called the API without a key")

    mock_http(handler)
    ok, detail = rr.check_key("   ")
    assert not ok
    assert detail == "No API key saved."
