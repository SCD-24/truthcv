"""jobfeeds/arbeitnow.py: client-side matching, pagination, and failure handling."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
import pytest

from agentconfig.store import JobProfile
from jobfeeds import arbeitnow as an

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)
NOW_TS = int(NOW.timestamp())


def _profile(**kwargs) -> JobProfile:
    base = {"name": "p", "enabled": True, "keywords": ["platform engineer"]}
    base.update(kwargs)
    return JobProfile(**base)


def _job(**kwargs) -> dict:
    base = {
        "slug": "acme-platform-engineer",
        "company_name": "Acme",
        "title": "Senior Platform Engineer",
        "description": "<p>Great role</p>",
        "remote": True,
        "url": "https://www.arbeitnow.com/view/acme-platform-engineer",
        "tags": ["kubernetes"],
        "job_types": ["Full-time"],
        "location": "Berlin",
        "created_at": NOW_TS - 3600,
    }
    base.update(kwargs)
    return base


_REAL_CLIENT = httpx.Client


def _client(handler):
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


def _page(data, next_url=None):
    return httpx.Response(200, json={"data": data, "links": {"next": next_url}, "meta": {}})


def test_keyword_match_on_title_or_tags(mock_http):
    mock_http(lambda r: _page([_job(title="Backend Dev", tags=["platform engineer"])]))
    result = an.fetch_postings([_profile()], now=NOW)
    assert result.error == ""
    assert len(result.postings) == 1
    assert result.postings[0].source == "arbeitnow"
    assert result.postings[0].company == "Acme"


def test_no_keyword_match_yields_no_postings(mock_http):
    mock_http(lambda r: _page([_job(title="Sales Rep", tags=["sales"])]))
    result = an.fetch_postings([_profile()], now=NOW)
    assert result.postings == []
    assert result.error == ""


def test_remote_only_profile_keeps_only_remote_jobs(mock_http):
    mock_http(
        lambda r: _page(
            [
                _job(title="Platform Engineer A", remote=True, url="https://www.arbeitnow.com/view/a"),
                _job(title="Platform Engineer B", remote=False, url="https://www.arbeitnow.com/view/b"),
            ]
        )
    )
    result = an.fetch_postings([_profile(remote_model="remote")], now=NOW)
    assert [p.url for p in result.postings] == ["https://www.arbeitnow.com/view/a"]


def test_unset_remote_model_keeps_remote_and_drops_onsite(mock_http):
    mock_http(
        lambda r: _page(
            [
                _job(title="Platform Engineer A", remote=True, url="https://www.arbeitnow.com/view/a"),
                _job(title="Platform Engineer B", remote=False, url="https://www.arbeitnow.com/view/b"),
            ]
        )
    )
    result = an.fetch_postings([_profile()], now=NOW)
    assert [p.url for p in result.postings] == ["https://www.arbeitnow.com/view/a"]


def test_hybrid_remote_model_keeps_remote_and_drops_onsite(mock_http):
    mock_http(
        lambda r: _page(
            [
                _job(title="Platform Engineer A", remote=True, url="https://www.arbeitnow.com/view/a"),
                _job(title="Platform Engineer B", remote=False, url="https://www.arbeitnow.com/view/b"),
            ]
        )
    )
    result = an.fetch_postings([_profile(remote_model="hybrid")], now=NOW)
    assert [p.url for p in result.postings] == ["https://www.arbeitnow.com/view/a"]


def test_onsite_profile_keeps_only_onsite_jobs(mock_http):
    mock_http(
        lambda r: _page(
            [
                _job(title="Platform Engineer A", remote=True, url="https://www.arbeitnow.com/view/a"),
                _job(title="Platform Engineer B", remote=False, url="https://www.arbeitnow.com/view/b"),
            ]
        )
    )
    result = an.fetch_postings([_profile(remote_model="onsite")], now=NOW)
    assert [p.url for p in result.postings] == ["https://www.arbeitnow.com/view/b"]


def test_location_filter_matches_substring_or_remote(mock_http):
    mock_http(
        lambda r: _page(
            [
                _job(title="Platform Engineer A", remote=False, location="Munich", url="https://www.arbeitnow.com/view/a"),
                _job(title="Platform Engineer B", remote=False, location="Berlin", url="https://www.arbeitnow.com/view/b"),
                _job(title="Platform Engineer C", remote=True, location="Paris", url="https://www.arbeitnow.com/view/c"),
            ]
        )
    )
    # An onsite profile needs the location substring; the remote posting is
    # dropped by remote_model, Munich by location.
    onsite = an.fetch_postings([_profile(remote_model="onsite", locations=["berlin"])], now=NOW)
    assert {p.url for p in onsite.postings} == {"https://www.arbeitnow.com/view/b"}
    # The default (remote-only) profile keeps the remote posting regardless of
    # its location, since a remote job has no fixed location to match.
    remote = an.fetch_postings([_profile(locations=["berlin"])], now=NOW)
    assert {p.url for p in remote.postings} == {"https://www.arbeitnow.com/view/c"}


def test_rejected_role_types_drop_matching_titles(mock_http):
    mock_http(lambda r: _page([_job(title="Platform Engineer Intern")]))
    result = an.fetch_postings([_profile(rejected_role_types=["intern"])], now=NOW)
    assert result.postings == []


def test_age_filter_uses_unix_seconds(mock_http):
    stale = _job(title="Platform Engineer Old", created_at=NOW_TS - 100 * 86400, url="https://www.arbeitnow.com/view/old")
    fresh = _job(title="Platform Engineer New", created_at=NOW_TS - 3600, url="https://www.arbeitnow.com/view/new")
    mock_http(lambda r: _page([stale, fresh]))
    result = an.fetch_postings([_profile()], max_posting_age_days=30, now=NOW)
    assert [p.url for p in result.postings] == ["https://www.arbeitnow.com/view/new"]


def test_homepage_url_is_dropped(mock_http):
    mock_http(
        lambda r: _page(
            [
                _job(title="Platform Engineer Root", url="https://www.preiswecker.com/"),
                _job(title="Platform Engineer Bare", url="https://www.preiswecker.com"),
            ]
        )
    )
    result = an.fetch_postings([_profile()], now=NOW)
    assert result.postings == []


def test_pagination_stops_on_missing_next(mock_http):
    calls = []

    def handler(request):
        page = request.url.params.get("page")
        calls.append(page)
        return _page([_job(title=f"Platform Engineer {page}", url=f"https://www.arbeitnow.com/view/{page}")], next_url=None)

    mock_http(handler)
    result = an.fetch_postings([_profile()], now=NOW)
    assert calls == ["1"]
    assert len(result.postings) == 1


def test_pagination_stops_on_empty_data(mock_http):
    calls = []

    def handler(request):
        page = request.url.params.get("page")
        calls.append(page)
        if page == "1":
            return _page(
                [_job(title="Platform Engineer 1", url="https://www.arbeitnow.com/view/1")],
                next_url="https://www.arbeitnow.com/api/job-board-api?page=2",
            )
        return _page([], next_url="https://www.arbeitnow.com/api/job-board-api?page=3")

    mock_http(handler)
    result = an.fetch_postings([_profile()], now=NOW)
    assert calls == ["1", "2"]
    assert len(result.postings) == 1


def test_http_500_returns_error_without_raising(mock_http):
    mock_http(lambda r: httpx.Response(500, text="boom"))
    result = an.fetch_postings([_profile()], now=NOW)
    assert result.postings == []
    assert "Arbeitnow" in result.error


def test_deadline_already_passed_makes_no_request(mock_http):
    calls = []
    mock_http(lambda r: calls.append(1) or _page([]))
    result = an.fetch_postings([_profile()], now=NOW, deadline=time.monotonic() - 1)
    assert calls == []
    assert result.postings == []
