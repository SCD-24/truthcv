"""jobfeeds/remoterocketship.py: profile→filters mapping, response parsing, failure handling."""

from __future__ import annotations

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

    assert len(calls) == 3  # 0s, 5s, 10s — the 4th starts past the 12s budget
    assert len(result.postings) == 3  # what was collected is kept, not discarded
    assert "too slow" in result.error


def test_a_request_never_outlives_the_remaining_budget(mock_http, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(rr.time, "monotonic", lambda: clock["t"])
    timeouts = []

    def handler(request):
        timeouts.append(request.extensions["timeout"]["read"])
        clock["t"] += 7.0
        return httpx.Response(200, json={"jobOpenings": []})

    mock_http(handler)
    rr.fetch_postings([_profile(name="a"), _profile(name="b")], "k", now=NOW)
    assert timeouts[0] == rr.TIMEOUT_SECONDS
    # 7s spent, 5s of budget left — the second request must not be allowed 8s.
    assert timeouts[1] == pytest.approx(5.0)


def test_the_budget_is_below_the_agents_config_fetch_timeout():
    """The two numbers are a contract across two languages. agent-config.js
    allows 30s for job_config; the budget must leave room for the rest of the
    config route on top of it."""
    assert rr.BUDGET_SECONDS < 30
    assert rr.TIMEOUT_SECONDS <= rr.BUDGET_SECONDS


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
