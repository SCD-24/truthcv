"""API-backed job boards: catalog behaviour, the key routes, and feed opt-in."""

from __future__ import annotations

import threading

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from agentconfig import boards, dorks
from agentconfig.store import JobProfile
from api.main import app

_REAL_CLIENT = httpx.Client


@pytest.fixture()
def client(data_dir, monkeypatch):
    # A saveable key needs encryption available; the env fallback is cleared so
    # a key on the developer's machine cannot make an unset store look set.
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("REMOTE_ROCKETSHIP_API_KEY", raising=False)
    return TestClient(app)


@pytest.fixture()
def mock_http(monkeypatch):
    def install(handler):
        class Patched(_REAL_CLIENT):  # type: ignore[misc,valid-type]
            def __init__(self, *args, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*args, **kw)

        monkeypatch.setattr(httpx, "Client", Patched)

    return install


# --- catalog ---------------------------------------------------------------


def test_remote_rocketship_is_api_backed_and_not_a_default():
    assert boards.is_api_source("remoterocketship")
    assert boards.is_api_source("RemoteRocketship")
    assert not boards.is_default_source("remoterocketship")
    assert not boards.is_api_source("ashby")
    assert not boards.is_api_source("jobs.acme.com")


def test_the_boards_raw_domain_is_recognised_as_api_backed_too():
    """The add-a-board control also accepts a typed domain. Recognising only
    the catalog key would give that operator a Google dork against the
    aggregator's listing pages and a sign-in button for a session that can
    never authenticate the feed."""
    assert boards.is_api_source("remoterocketship.com")
    assert boards.resolve_signin_url("remoterocketship.com") == ""
    profile = JobProfile(name="p", enabled=True, keywords=["backend"])
    entries = dorks.compose_profile_queries(profile, None, ["remoterocketship.com"])
    assert {e["source"] for e in entries} == set(dorks.DEFAULT_BOARD_DOMAINS)


def test_a_board_added_as_a_raw_domain_still_reaches_the_feed(client, data_dir, mock_http):
    client.put("/api/agent/config", json={
        "jobBoards": [{"source": "remoterocketship.com"}],
        "profiles": [{"name": "p", "enabled": True, "keywords": ["backend"]}],
    })
    client.put("/api/job-boards/remoterocketship.com/key", json={"apiKey": "rr_secret"})
    mock_http(
        lambda r: httpx.Response(
            200, json={"jobOpenings": [{"roleTitle": "T", "url": "https://acme.example/1"}]}
        )
    )
    got = client.get("/api/agent/config?include_feed=true").json()
    assert [p["url"] for p in got["feedPostings"]] == ["https://acme.example/1"]


def test_an_api_board_has_no_signin_url_even_with_an_override():
    """There is no browser session to open. Resolving one would put a "Sign in"
    button on a board that can only ever be authenticated with a saved key."""
    assert boards.resolve_signin_url("remoterocketship") == ""
    assert boards.resolve_signin_url("remoterocketship", "https://example.com/login") == ""


def test_an_api_board_composes_no_google_dork():
    """The postings are pulled from the API. A site: dork for the same board
    would send the agent to the aggregator's own listing pages instead."""
    profile = JobProfile(name="p", enabled=True, keywords=["backend"])
    entries = dorks.compose_profile_queries(profile, None, ["remoterocketship"])
    assert {e["source"] for e in entries} == set(dorks.DEFAULT_BOARD_DOMAINS)
    assert not any("remoterocketship" in e["query"] for e in entries)


def test_a_non_api_extra_board_still_composes_a_dork():
    """Guards the exclusion above against over-reach: only API boards are skipped."""
    profile = JobProfile(name="p", enabled=True, keywords=["backend"])
    entries = dorks.compose_profile_queries(profile, None, ["remoterocketship", "linkedin"])
    assert "linkedin.com/jobs" in {e["source"] for e in entries}


# --- resolved board list ---------------------------------------------------


def test_configured_api_board_is_flagged_and_carries_no_signin_url(client, data_dir):
    r = client.put("/api/agent/config", json={"jobBoards": [{"source": "remoterocketship"}]})
    assert r.status_code == 200
    board = next(b for b in r.json()["jobBoards"] if b["source"] == "remoterocketship")
    assert board["isApi"] is True
    assert board["isDefault"] is False
    assert board["effectiveSigninUrl"] == ""
    assert all(b["isApi"] is False for b in r.json()["jobBoards"] if b["source"] != "remoterocketship")


# --- key routes ------------------------------------------------------------


def test_key_status_starts_unset_and_flips_after_a_put(client, data_dir, monkeypatch):
    monkeypatch.delenv("REMOTE_ROCKETSHIP_API_KEY", raising=False)
    assert client.get("/api/job-boards/remoterocketship/key").json()["keySet"] is False

    r = client.put("/api/job-boards/remoterocketship/key", json={"apiKey": "rr_secret"})
    assert r.status_code == 200
    assert r.json()["keySet"] is True
    assert client.get("/api/job-boards/remoterocketship/key").json()["keySet"] is True


def test_the_key_is_never_returned_by_any_route(client, data_dir):
    client.put("/api/job-boards/remoterocketship/key", json={"apiKey": "rr_super_secret"})
    for path in ("/api/job-boards/remoterocketship/key", "/api/agent/config"):
        assert "rr_super_secret" not in client.get(path).text


def test_an_empty_key_clears_the_stored_one(client, data_dir, monkeypatch):
    monkeypatch.delenv("REMOTE_ROCKETSHIP_API_KEY", raising=False)
    client.put("/api/job-boards/remoterocketship/key", json={"apiKey": "rr_secret"})
    r = client.put("/api/job-boards/remoterocketship/key", json={"apiKey": ""})
    assert r.json()["keySet"] is False


def test_key_routes_reject_a_board_that_is_not_api_backed(client, data_dir):
    for method, path in (
        ("get", "/api/job-boards/ashby/key"),
        ("post", "/api/job-boards/ashby/key/test"),
    ):
        assert getattr(client, method)(path).status_code == 404
    assert client.put("/api/job-boards/ashby/key", json={"apiKey": "x"}).status_code == 404


def test_key_test_route_reports_the_boards_own_message(client, data_dir, mock_http):
    client.put("/api/job-boards/remoterocketship/key", json={"apiKey": "rr_secret"})
    mock_http(lambda r: httpx.Response(403, json={"message": "Active subscription required"}))
    body = client.post("/api/job-boards/remoterocketship/key/test").json()
    assert body["ok"] is False
    assert body["detail"] == "Active subscription required"


# --- feed opt-in -----------------------------------------------------------


def _configure(client, monkeypatch):
    monkeypatch.delenv("REMOTE_ROCKETSHIP_API_KEY", raising=False)
    client.put(
        "/api/agent/config",
        json={
            "jobBoards": [{"source": "remoterocketship"}],
            "profiles": [{"name": "p", "enabled": True, "keywords": ["backend"]}],
        },
    )
    client.put("/api/job-boards/remoterocketship/key", json={"apiKey": "rr_secret"})


def test_a_plain_config_get_never_calls_the_feed(client, data_dir, mock_http, monkeypatch):
    """The web UI loads this endpoint on two pages. Making every page load wait
    on — or fail with — a third-party API buys nothing, since the browser never
    renders the postings."""
    _configure(client, monkeypatch)

    def handler(request):  # pragma: no cover — must never run
        raise AssertionError("GET /agent/config called the feed without include_feed")

    mock_http(handler)
    got = client.get("/api/agent/config").json()
    assert got["feedPostings"] == []
    assert got["feedError"] == ""


def test_include_feed_returns_postings(client, data_dir, mock_http, monkeypatch):
    _configure(client, monkeypatch)
    mock_http(
        lambda r: httpx.Response(
            200,
            json={
                "jobOpenings": [
                    {
                        "roleTitle": "Backend Engineer",
                        "url": "https://acme.example/jobs/1",
                        "company": {"name": "Acme"},
                    }
                ]
            },
        )
    )
    got = client.get("/api/agent/config?include_feed=true").json()
    assert [p["url"] for p in got["feedPostings"]] == ["https://acme.example/jobs/1"]
    assert got["feedPostings"][0]["source"] == "remoterocketship"
    assert got["feedError"] == ""


def test_include_feed_without_the_board_configured_calls_nothing(client, data_dir, mock_http, monkeypatch):
    """The board being in the config is what makes the feed opt-in — a key left
    in secrets.enc from an earlier trial must not resurrect it."""
    monkeypatch.delenv("REMOTE_ROCKETSHIP_API_KEY", raising=False)
    client.put("/api/job-boards/remoterocketship/key", json={"apiKey": "rr_secret"})

    def handler(request):  # pragma: no cover — must never run
        raise AssertionError("the feed ran for a board that is not configured")

    mock_http(handler)
    assert client.get("/api/agent/config?include_feed=true").json()["feedPostings"] == []


def test_an_already_screened_posting_is_omitted_and_counted(client, data_dir, mock_http, monkeypatch):
    """The agent stops re-screening postings that come back created:false: a
    posting the ledger already has a screening for is dropped from the feed,
    and the drop is reported so it is visible rather than a silently shorter
    feed."""
    from screening import store as screening_store

    _configure(client, monkeypatch)
    screened_url = "https://acme.example/jobs/1"
    screening_store.create_or_get(
        {"company": "Acme", "role": "Backend Engineer", "url": screened_url, "verdict": "rejected"}
    )
    mock_http(
        lambda r: httpx.Response(
            200,
            json={
                "jobOpenings": [
                    {"roleTitle": "Backend Engineer", "url": screened_url},
                    {"roleTitle": "Other Role", "url": "https://acme.example/jobs/2"},
                ]
            },
        )
    )
    got = client.get("/api/agent/config?include_feed=true").json()
    assert [p["url"] for p in got["feedPostings"]] == ["https://acme.example/jobs/2"]
    assert got["feedAlreadyScreened"] == 1


def test_an_unread_placeholder_screening_does_not_hide_its_posting(client, data_dir, mock_http, monkeypatch):
    """A placeholder holds no judgement (see screened_dedupe_keys), so the
    posting it stands in for must still reach the agent to be screened for
    real."""
    from screening import store as screening_store

    _configure(client, monkeypatch)
    placeholder_url = "https://acme.example/jobs/1"
    screening_store.create_or_get(
        {
            "company": "Acme",
            "role": "Backend Engineer",
            "url": placeholder_url,
            "verdict": "",
            "screening_blocker": "not_found",
        }
    )
    mock_http(
        lambda r: httpx.Response(
            200, json={"jobOpenings": [{"roleTitle": "Backend Engineer", "url": placeholder_url}]}
        )
    )
    got = client.get("/api/agent/config?include_feed=true").json()
    assert [p["url"] for p in got["feedPostings"]] == [placeholder_url]
    assert got["feedAlreadyScreened"] == 0


def test_feed_already_screened_is_zero_without_include_feed(client, data_dir, mock_http, monkeypatch):
    _configure(client, monkeypatch)

    def handler(request):  # pragma: no cover — must never run
        raise AssertionError("GET /agent/config called the feed without include_feed")

    mock_http(handler)
    got = client.get("/api/agent/config").json()
    assert got["feedAlreadyScreened"] == 0


def test_a_feed_failure_does_not_break_the_config_response(client, data_dir, mock_http, monkeypatch):
    """The agent fetches its whole configuration from this route. A Remote
    Rocketship outage must cost the feed, not the run."""
    _configure(client, monkeypatch)
    mock_http(lambda r: httpx.Response(500, json={"message": "Unable to fetch jobs"}))
    r = client.get("/api/agent/config?include_feed=true")
    assert r.status_code == 200
    got = r.json()
    assert got["feedPostings"] == []
    assert got["feedError"] == "Unable to fetch jobs"
    assert got["profiles"][0]["name"] == "p"
    assert got["searchQueries"] != []


# --- ATS fan-out -------------------------------------------------------


def test_the_feed_fans_out_across_remote_rocketship_and_watchlist_ats_boards(client, data_dir, mock_http, monkeypatch):
    """Two independent sources, merged: Remote Rocketship (key-gated) and each
    watchlist company's own ATS API (gated only on a recognised ats, no key)."""
    from companyboards import store as board_store

    _configure(client, monkeypatch)
    client.put("/api/agent/config", json={"targetCompanies": ["Acme"]})
    board_store.record("Acme", "https://boards.greenhouse.io/acme", "greenhouse")

    def handler(request):
        if "greenhouse" in request.url.host:
            return httpx.Response(
                200, json={"jobs": [{"title": "GH Role", "absolute_url": "https://acme.example/gh/1"}]}
            )
        return httpx.Response(
            200, json={"jobOpenings": [{"roleTitle": "RR Role", "url": "https://acme.example/rr/1"}]}
        )

    mock_http(handler)
    got = client.get("/api/agent/config?include_feed=true").json()
    urls = {p["url"] for p in got["feedPostings"]}
    assert urls == {"https://acme.example/gh/1", "https://acme.example/rr/1"}
    assert got["feedError"] == ""
    assert all(p["tier"] == "api" for p in got["feedPostings"])


def test_the_feed_dedupes_across_sources_by_url(client, data_dir, mock_http, monkeypatch):
    """The same URL surfaced by both sources appears once in the merged feed."""
    from companyboards import store as board_store

    _configure(client, monkeypatch)
    client.put("/api/agent/config", json={"targetCompanies": ["Acme"]})
    board_store.record("Acme", "https://boards.greenhouse.io/acme", "greenhouse")
    shared_url = "https://acme.example/shared/1"

    def handler(request):
        if "greenhouse" in request.url.host:
            return httpx.Response(200, json={"jobs": [{"title": "GH Role", "absolute_url": shared_url}]})
        return httpx.Response(200, json={"jobOpenings": [{"roleTitle": "RR Role", "url": shared_url}]})

    mock_http(handler)
    got = client.get("/api/agent/config?include_feed=true").json()
    assert [p["url"] for p in got["feedPostings"]] == [shared_url]


def test_one_sources_failure_does_not_drop_the_others_postings(client, data_dir, mock_http, monkeypatch):
    """Remote Rocketship failing must not empty out a working ATS fetch, and the
    failure is still surfaced in feed_error."""
    from companyboards import store as board_store

    _configure(client, monkeypatch)
    client.put("/api/agent/config", json={"targetCompanies": ["Acme"]})
    board_store.record("Acme", "https://boards.greenhouse.io/acme", "greenhouse")

    def handler(request):
        if "greenhouse" in request.url.host:
            return httpx.Response(
                200, json={"jobs": [{"title": "GH Role", "absolute_url": "https://acme.example/gh/1"}]}
            )
        return httpx.Response(500, json={"message": "Unable to fetch jobs"})

    mock_http(handler)
    got = client.get("/api/agent/config?include_feed=true").json()
    assert [p["url"] for p in got["feedPostings"]] == ["https://acme.example/gh/1"]
    assert "Unable to fetch jobs" in got["feedError"]


def test_an_ats_board_reaches_the_feed_with_no_key_configured(client, data_dir, mock_http, monkeypatch):
    """The ATS path needs no key at all — only a recognised company board."""
    from companyboards import store as board_store

    monkeypatch.delenv("REMOTE_ROCKETSHIP_API_KEY", raising=False)
    client.put("/api/agent/config", json={"targetCompanies": ["Acme"]})
    board_store.record("Acme", "https://boards.greenhouse.io/acme", "greenhouse")

    mock_http(
        lambda r: httpx.Response(
            200, json={"jobs": [{"title": "GH Role", "absolute_url": "https://acme.example/gh/1"}]}
        )
    )
    got = client.get("/api/agent/config?include_feed=true").json()
    assert [p["url"] for p in got["feedPostings"]] == ["https://acme.example/gh/1"]


def test_the_combined_fetch_shares_one_deadline_between_both_sources(client, data_dir, mock_http, monkeypatch):
    """BLOCKING 1 / task t-1: Remote Rocketship and the ATS fetch used to each
    get their OWN independent 20s budget, so together they could approach 40s
    against agent-config.js's fixed 30s socket timeout for job_config — the
    exact abort the feed's never-raise design exists to prevent. They must
    instead share ONE deadline value rather than each computing a fresh
    BUDGET_SECONDS window of its own.

    The two fetches now run concurrently on their own threads (see
    api/routes.py's ``_fetch_feed_postings``) rather than one after another,
    so there is no longer a well-defined "first fetcher's spend eats into the
    second's budget" moment to pin a fake clock to — whichever thread the
    scheduler happens to run first is not something a test should assume.
    What IS still guaranteed, and worth proving, is that both fetchers are
    handed the exact same ``deadline`` object: this captures the ``deadline``
    kwarg each of the two underlying calls actually receives and checks they
    match, regardless of which one the scheduler happens to start first."""
    from companyboards import store as board_store
    from jobfeeds import ats as ats_module
    from jobfeeds import remoterocketship as rr_module

    _configure(client, monkeypatch)
    client.put("/api/agent/config", json={"targetCompanies": ["Acme"]})
    board_store.record("Acme", "https://boards.greenhouse.io/acme", "greenhouse")

    deadlines_seen = {}
    real_rr_fetch = rr_module.fetch_postings
    real_ats_fetch = ats_module.fetch_ats_postings

    def spy_rr_fetch(*args, **kwargs):
        deadlines_seen["remoterocketship"] = kwargs.get("deadline")
        return real_rr_fetch(*args, **kwargs)

    def spy_ats_fetch(*args, **kwargs):
        deadlines_seen["ats"] = kwargs.get("deadline")
        return real_ats_fetch(*args, **kwargs)

    monkeypatch.setattr(rr_module, "fetch_postings", spy_rr_fetch)
    monkeypatch.setattr(ats_module, "fetch_ats_postings", spy_ats_fetch)
    mock_http(lambda r: httpx.Response(200, json={"jobs": [], "jobOpenings": []}))

    client.get("/api/agent/config?include_feed=true")

    assert deadlines_seen.get("remoterocketship") is not None
    assert deadlines_seen.get("ats") is not None
    assert deadlines_seen["remoterocketship"] == deadlines_seen["ats"]


def test_remote_rocketship_and_ats_are_fetched_concurrently_not_serially(client, data_dir, mock_http, monkeypatch):
    """Task t-1: the two sources run on separate threads sharing one deadline,
    not one after another. Proven with a two-party Barrier: each mock handler
    waits on it before responding, so if the fetches ran serially the SECOND
    one would be a lone party and time out waiting for a partner that never
    arrives — this only completes, with both sources' postings merged, because
    both threads reach the barrier together."""
    from companyboards import store as board_store

    _configure(client, monkeypatch)
    client.put("/api/agent/config", json={"targetCompanies": ["Acme"]})
    board_store.record("Acme", "https://boards.greenhouse.io/acme", "greenhouse")

    barrier = threading.Barrier(2, timeout=5)

    def handler(request):
        barrier.wait()
        if "greenhouse" in request.url.host:
            return httpx.Response(
                200, json={"jobs": [{"title": "GH Role", "absolute_url": "https://acme.example/gh/1"}]}
            )
        return httpx.Response(
            200, json={"jobOpenings": [{"roleTitle": "RR Role", "url": "https://acme.example/rr/1"}]}
        )

    mock_http(handler)
    got = client.get("/api/agent/config?include_feed=true").json()
    urls = {p["url"] for p in got["feedPostings"]}
    assert urls == {"https://acme.example/gh/1", "https://acme.example/rr/1"}
    assert got["feedError"] == ""
