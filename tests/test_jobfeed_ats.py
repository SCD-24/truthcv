"""jobfeeds/ats.py: per-company ATS dispatch, response parsing, failure isolation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from companyboards.store import CompanyBoard
from jobfeeds import ats

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)


def _board(**kwargs) -> CompanyBoard:
    base = {"company": "Widgetco", "careers_url": "https://boards.greenhouse.io/widgetco", "ats": "greenhouse"}
    base.update(kwargs)
    return CompanyBoard(**base)


# Captured once at import, before any test patches httpx.Client — reading
# httpx.Client inside the factory would, on a second install() in the same
# test, subclass the already-patched class and inherit the FIRST handler.
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


# --- fixtures: obviously invented data --------------------------------------

_GREENHOUSE_BODY = {
    "jobs": [
        {
            "title": "Zorkmid Alignment Engineer",
            "absolute_url": "https://boards.greenhouse.io/widgetco/jobs/1",
            "updated_at": "2026-08-26T09:00:00+00:00",
        }
    ]
}

_LEVER_BODY = [
    {
        "text": "Sprocket Wrangler",
        "hostedUrl": "https://jobs.lever.co/gizmoinc/1",
        "createdAt": int(datetime(2026, 8, 26, tzinfo=timezone.utc).timestamp() * 1000),
        "categories": {"commitment": "Full-time"},
    }
]

_ASHBY_BODY = {
    "jobs": [
        {
            "title": "Flibbertigibbet Analyst",
            "jobUrl": "https://jobs.ashbyhq.com/doohickeyco/1",
            "publishedAt": "2026-08-26T09:00:00Z",
            "employmentType": "FullTime",
        }
    ]
}

_PERSONIO_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
  <position>
    <id>42</id>
    <name>Whatchamacallit Specialist</name>
    <employmentType>full-time</employmentType>
    <createdAt>2026-08-26T09:00:00+00:00</createdAt>
  </position>
</workzag-jobs>
"""


def _handler_for(bodies: dict[str, object]):
    """Route a mock request to a canned response keyed by hostname."""

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host not in bodies:
            return httpx.Response(404, text="not found")
        body = bodies[host]
        if isinstance(body, str):
            return httpx.Response(200, text=body)
        return httpx.Response(200, json=body)

    return handler


# --- per-ATS shape parsing + slug derivation --------------------------------


def test_greenhouse_shape_parses_into_feed_posting(mock_http):
    mock_http(_handler_for({"boards-api.greenhouse.io": _GREENHOUSE_BODY}))
    board = _board(company="Widgetco", careers_url="https://boards.greenhouse.io/widgetco", ats="greenhouse")
    result = ats.fetch_ats_postings([board], now=NOW)

    assert result.error == ""
    assert len(result.postings) == 1
    posting = result.postings[0]
    assert posting.title == "Zorkmid Alignment Engineer"
    assert posting.company == "Widgetco"
    assert posting.url == "https://boards.greenhouse.io/widgetco/jobs/1"
    assert posting.source == "greenhouse"
    assert posting.tier == "api"
    assert posting.profile == ""


def test_lever_shape_parses_into_feed_posting(mock_http):
    mock_http(_handler_for({"api.lever.co": _LEVER_BODY}))
    board = _board(company="Gizmo Inc", careers_url="https://jobs.lever.co/gizmoinc", ats="Lever")
    result = ats.fetch_ats_postings([board], now=NOW)

    assert result.error == ""
    assert len(result.postings) == 1
    posting = result.postings[0]
    assert posting.title == "Sprocket Wrangler"
    assert posting.url == "https://jobs.lever.co/gizmoinc/1"
    assert posting.employment_type == "Full-time"
    assert posting.source == "lever"
    assert posting.tier == "api"


def test_ashby_shape_parses_into_feed_posting(mock_http):
    mock_http(_handler_for({"api.ashbyhq.com": _ASHBY_BODY}))
    board = _board(company="Doohickey Co", careers_url="https://jobs.ashbyhq.com/doohickeyco", ats="ASHBY")
    result = ats.fetch_ats_postings([board], now=NOW)

    assert result.error == ""
    assert len(result.postings) == 1
    posting = result.postings[0]
    assert posting.title == "Flibbertigibbet Analyst"
    assert posting.url == "https://jobs.ashbyhq.com/doohickeyco/1"
    assert posting.employment_type == "FullTime"
    assert posting.source == "ashby"


def test_personio_shape_parses_into_feed_posting(mock_http):
    mock_http(_handler_for({"thingamajig.jobs.personio.de": _PERSONIO_BODY}))
    board = _board(company="Thingamajig LLC", careers_url="https://thingamajig.jobs.personio.de", ats="personio")
    result = ats.fetch_ats_postings([board], now=NOW)

    assert result.error == ""
    assert len(result.postings) == 1
    posting = result.postings[0]
    assert posting.title == "Whatchamacallit Specialist"
    assert posting.url == "https://thingamajig.jobs.personio.de/job/42"
    assert posting.employment_type == "full-time"
    assert posting.source == "personio"


def test_personio_url_is_built_from_the_derived_slug_not_the_raw_careers_url(mock_http):
    """Regression: careers_url can carry a path beyond the board root (e.g. a
    link straight to one posting). The fetch itself is unaffected (only the
    hostname's first label matters), but the OLD code reconstructed each
    posting's URL by appending to the raw careers_url string, producing
    "https://acme.jobs.personio.de/job/9/job/42" — a 404 the agent would open.
    The URL must instead be built from the slug the fetch actually used."""
    mock_http(_handler_for({"acme.jobs.personio.de": _PERSONIO_BODY}))
    board = _board(company="Acme", careers_url="https://acme.jobs.personio.de/job/9", ats="personio")
    result = ats.fetch_ats_postings([board], now=NOW)

    assert result.error == ""
    assert len(result.postings) == 1
    assert result.postings[0].url == "https://acme.jobs.personio.de/job/42"


def test_personios_own_position_url_is_preferred_over_reconstruction(mock_http):
    body = """<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
  <position>
    <id>42</id>
    <name>Whatchamacallit Specialist</name>
    <employmentType>full-time</employmentType>
    <createdAt>2026-08-26T09:00:00+00:00</createdAt>
    <url>https://thingamajig.jobs.personio.de/job/42/whatchamacallit-specialist</url>
  </position>
</workzag-jobs>
"""
    mock_http(_handler_for({"thingamajig.jobs.personio.de": body}))
    board = _board(company="Thingamajig LLC", careers_url="https://thingamajig.jobs.personio.de", ats="personio")
    result = ats.fetch_ats_postings([board], now=NOW)

    assert result.postings[0].url == "https://thingamajig.jobs.personio.de/job/42/whatchamacallit-specialist"


def test_personio_position_with_no_buildable_url_is_dropped():
    """Unit-level: if a fetch somehow ran without a derivable slug and the feed
    gave no per-position URL either, the position must be dropped rather than
    emitted with a guessed deep link."""
    position = ET.fromstring("<position><id>1</id><name>No URL Role</name></position>")
    assert ats._personio_position_url(position, "", "1") == ""


def test_token_derivation_uses_the_careers_url_shape_for_each_ats(mock_http):
    seen_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append((request.url.host, request.url.path))
        return httpx.Response(404, text="not found")

    mock_http(handler)
    boards = [
        _board(careers_url="https://boards.greenhouse.io/acme-token", ats="greenhouse"),
        _board(careers_url="https://jobs.lever.co/acme-slug", ats="lever"),
        _board(careers_url="https://jobs.ashbyhq.com/acme-name", ats="ashby"),
        _board(careers_url="https://acme-sub.jobs.personio.de", ats="personio"),
    ]
    ats.fetch_ats_postings(boards, now=NOW)

    assert ("boards-api.greenhouse.io", "/v1/boards/acme-token/jobs") in seen_paths
    assert ("api.lever.co", "/v0/postings/acme-slug") in seen_paths
    assert ("api.ashbyhq.com", "/posting-api/job-board/acme-name") in seen_paths
    assert ("acme-sub.jobs.personio.de", "/xml") in seen_paths


def test_greenhouse_embed_widget_shape_derives_the_token_from_the_for_param(mock_http):
    """Fix 3: Greenhouse's documented embed shape,
    "https://boards.greenhouse.io/embed/job_board?for=acme", has "embed" as
    its first path segment. Taking that literally as the board token risks
    fetching (and presenting under this company's name) a board named
    "embed", if one exists. The real token is the `for` query parameter."""
    mock_http(_handler_for({"boards-api.greenhouse.io": _GREENHOUSE_BODY}))
    board = _board(
        company="Widgetco",
        careers_url="https://boards.greenhouse.io/embed/job_board?for=widgetco",
        ats="greenhouse",
    )
    result = ats.fetch_ats_postings([board], now=NOW)
    assert result.error == ""
    assert len(result.postings) == 1
    assert result.postings[0].company == "Widgetco"


def test_greenhouse_embed_widget_segment_is_matched_case_insensitively(mock_http):
    """Regression: the segment was compared to "embed" case-sensitively, so
    "https://boards.greenhouse.io/Embed/job_board?for=widgetco" fell through to
    being treated as a real board named "Embed" instead of the embed widget
    shape — any real Greenhouse board actually named "Embed" would then be
    fetched and emitted under Widgetco's name with a stranger's apply URLs."""
    mock_http(_handler_for({"boards-api.greenhouse.io": _GREENHOUSE_BODY}))
    board = _board(
        company="Widgetco",
        careers_url="https://boards.greenhouse.io/Embed/job_board?for=widgetco",
        ats="greenhouse",
    )
    result = ats.fetch_ats_postings([board], now=NOW)
    assert result.error == ""
    assert len(result.postings) == 1
    assert result.postings[0].company == "Widgetco"


def test_greenhouse_embed_widget_with_no_for_param_is_skipped_not_guessed(mock_http):
    """Without a `for` param there is no token to derive at all — this must
    not fall back to treating "embed" itself as a board token. Fix 2: this is
    ATS-HOSTED but tokenless, not "not an ATS-hosted board URL" — the host
    really is boards.greenhouse.io, so that message would be false."""

    def handler(request: httpx.Request):  # pragma: no cover — must never run
        raise AssertionError("fetch_ats_postings guessed \"embed\" as a board token")

    mock_http(handler)
    board = _board(
        company="Widgetco", careers_url="https://boards.greenhouse.io/embed/job_board", ats="greenhouse"
    )
    result = ats.fetch_ats_postings([board], now=NOW)
    assert result.postings == []
    assert "1 company board skipped" in result.error
    assert "ATS-hosted but no board token could be derived" in result.error
    assert "not an ATS-hosted board URL" not in result.error


def test_bare_ats_hosted_url_with_no_path_is_skipped_as_tokenless_not_unhosted(mock_http):
    """Fix 2: a bare "https://boards.greenhouse.io/" has no path segment to
    derive a token from, but the host IS boards.greenhouse.io — the note must
    say a token could not be derived, not that the URL isn't ATS-hosted."""

    def handler(request: httpx.Request):  # pragma: no cover — must never run
        raise AssertionError("fetch_ats_postings guessed a board id with no path segment")

    mock_http(handler)
    board = _board(company="Widgetco", careers_url="https://boards.greenhouse.io/", ats="greenhouse")
    result = ats.fetch_ats_postings([board], now=NOW)
    assert result.postings == []
    assert "ATS-hosted but no board token could be derived" in result.error
    assert "not an ATS-hosted board URL" not in result.error


# --- host validation: careers_url must be an ATS-hosted board URL ----------


def test_employer_careers_domain_is_skipped_not_guessed_as_a_board_token(mock_http):
    """Regression: "https://careers.robco.example.com/de" with ats
    "Greenhouse" (the exact shape tests/test_company_boards_store.py records)
    used to derive token "de" and fetch boards-api.greenhouse.io/v1/boards/de.
    Any real Greenhouse board whose token happens to be "de" would then have
    ITS postings emitted under RobCo's name with a stranger's apply URLs. The
    host is not an ATS board host, so this must be skipped without a request —
    but (fix 4) surfaced as an informational note, not left completely silent."""

    def handler(request: httpx.Request):  # pragma: no cover — must never run
        raise AssertionError("fetch_ats_postings guessed a board id from an employer domain")

    mock_http(handler)
    board = _board(
        company="RobCo GmbH", careers_url="https://careers.robco.example.com/de", ats="Greenhouse"
    )
    result = ats.fetch_ats_postings([board], now=NOW)
    assert result.postings == []
    assert "1 company board skipped" in result.error
    assert "ATS-hosted board URL" in result.error


def test_careers_domain_with_no_path_segment_is_skipped_not_errored(mock_http):
    """Regression: "https://careers.google.com" (the exact shape
    tests/test_company_boards_store.py records for Google/Lever) has no path
    segment, so the old first-path-segment derivation failed for every board
    recorded in the repo's own real shape. It must be skipped like an
    unrecognised ats (no request fired, no postings dropped as a failure),
    but — fix 4 — surfaced as an informational note rather than staying
    silent about why this board produced nothing."""

    def handler(request: httpx.Request):  # pragma: no cover — must never run
        raise AssertionError("fetch_ats_postings guessed a board id from an employer domain")

    mock_http(handler)
    board = _board(company="Google", careers_url="https://careers.google.com", ats="Lever")
    result = ats.fetch_ats_postings([board], now=NOW)
    assert result.postings == []
    assert "1 company board skipped" in result.error


def test_several_unhosted_boards_are_counted_together_in_one_note(mock_http):
    """Fix 4: the note must count across the whole fetch, and must not treat a
    genuinely working board's postings, or a separate real HTTP failure, as
    anything other than what they are."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "boards-api.greenhouse.io":
            return httpx.Response(
                200, json={"jobs": [{"title": "Good Role", "absolute_url": "https://good.example/1"}]}
            )
        return httpx.Response(404, text="not found")  # pragma: no cover — unhosted boards fire no request

    mock_http(handler)
    boards = [
        _board(company="Good Co", careers_url="https://boards.greenhouse.io/goodco", ats="greenhouse"),
        _board(company="RobCo", careers_url="https://careers.robco.example.com/de", ats="Greenhouse"),
        _board(company="Google", careers_url="https://careers.google.com", ats="Lever"),
    ]
    result = ats.fetch_ats_postings(boards, now=NOW)
    assert [p.url for p in result.postings] == ["https://good.example/1"]
    assert "2 company boards skipped" in result.error
    assert "ATS-hosted board URL" in result.error


def test_an_explicit_deadline_overrides_the_default_budget(mock_http, monkeypatch):
    """A caller fanning this fetch out alongside another source (see
    api/routes.py's _fetch_feed_postings) passes its own shared deadline; it
    must be honored instead of a fresh BUDGET_SECONDS window."""
    monkeypatch.setattr(ats.time, "monotonic", lambda: 0.0)
    timeouts = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, json=_GREENHOUSE_BODY)

    mock_http(handler)
    # A deadline 3s out — far tighter than the module's own 20s BUDGET_SECONDS
    # — must be what actually governs the request's timeout.
    ats.fetch_ats_postings([_board(ats="greenhouse")], now=NOW, deadline=3.0)
    assert timeouts[0] == pytest.approx(3.0)


class _TricklingStream(httpx.SyncByteStream):
    """A response body that arrives in several chunks, each individually well
    within any per-chunk timeout — the shape that can outlive a shared
    deadline if only the per-request timeout (a gap-between-bytes measure)
    bounds the read, per fix 5."""

    def __iter__(self):
        yield b'{"jobs": '
        yield b"[]}"


def test_a_trickling_response_cannot_outlive_the_shared_deadline(mock_http, monkeypatch):
    """Fix 5: httpx's per-request timeout bounds the GAP between chunks, not
    the read as a whole. A host that keeps sending one chunk just before each
    per-chunk timeout expires can otherwise stay open indefinitely — this
    pins that ``fetch_ats_postings`` still cuts the request off at the
    absolute shared deadline, deterministically, via a pinned clock (no real
    sleeping or network)."""
    # Deadline is 21s out. The clock ticks: 20.0 at the top of the fetch loop
    # (remaining = 1.0s, still positive, so the request is attempted), then
    # 22.0 and 24.0 as each streamed chunk is read — each read individually
    # would satisfy a generous per-chunk timeout, but the second one is
    # already past the absolute deadline of 21.0.
    ticks = iter([20.0, 22.0, 24.0])
    monkeypatch.setattr(ats.time, "monotonic", lambda: next(ticks, 24.0))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_TricklingStream())

    mock_http(handler)
    result = ats.fetch_ats_postings([_board(ats="greenhouse")], now=NOW, deadline=21.0)
    assert result.postings == []
    assert "exceeded the shared feed deadline" in result.error


# --- dispatch / skipping -----------------------------------------------------


def test_blank_or_unknown_ats_is_skipped_without_a_request(mock_http):
    def handler(request: httpx.Request):  # pragma: no cover — must never run
        raise AssertionError("fetch_ats_postings called out for an unrecognised ats")

    mock_http(handler)
    boards = [
        _board(ats=""),
        _board(ats="some-homegrown-tracker"),
    ]
    result = ats.fetch_ats_postings(boards, now=NOW)
    assert result.postings == []
    assert result.error == ""


# --- failure isolation --------------------------------------------------------


def test_one_companys_http_failure_does_not_empty_the_result(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "boards-api.greenhouse.io":
            return httpx.Response(404, text="board not found")
        return httpx.Response(200, json=_LEVER_BODY)

    mock_http(handler)
    boards = [
        _board(company="Deadco", careers_url="https://boards.greenhouse.io/deadco", ats="greenhouse"),
        _board(company="Gizmo Inc", careers_url="https://jobs.lever.co/gizmoinc", ats="lever"),
    ]
    result = ats.fetch_ats_postings(boards, now=NOW)

    assert len(result.postings) == 1
    assert result.postings[0].company == "Gizmo Inc"
    assert "404" in result.error


def test_transport_failure_is_isolated_and_reported_not_raised(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "boards-api.greenhouse.io":
            raise httpx.ConnectError("no route to host")
        return httpx.Response(200, json=_LEVER_BODY)

    mock_http(handler)
    boards = [
        _board(company="Deadco", careers_url="https://boards.greenhouse.io/deadco", ats="greenhouse"),
        _board(company="Gizmo Inc", careers_url="https://jobs.lever.co/gizmoinc", ats="lever"),
    ]
    result = ats.fetch_ats_postings(boards, now=NOW)

    assert len(result.postings) == 1
    assert "Could not reach Greenhouse" in result.error


# --- malformed / unexpected shapes -------------------------------------------


def test_unexpected_json_shape_is_handled_without_raising(mock_http):
    mock_http(_handler_for({"boards-api.greenhouse.io": {"nope": True}}))
    board = _board(ats="greenhouse")
    result = ats.fetch_ats_postings([board], now=NOW)
    assert result.postings == []
    assert result.error == ""


def test_non_json_body_is_handled_without_raising(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    mock_http(handler)
    result = ats.fetch_ats_postings([_board(ats="greenhouse")], now=NOW)
    assert result.postings == []
    assert "unexpected response shape" in result.error


def test_malformed_xml_is_handled_without_raising(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<workzag-jobs><position><id>1</id>")

    mock_http(handler)
    board = _board(company="Brokenco", careers_url="https://brokenco.jobs.personio.de", ats="personio")
    result = ats.fetch_ats_postings([board], now=NOW)
    assert result.postings == []
    assert "unexpected response shape" in result.error


def test_lever_non_list_body_is_handled_without_raising(mock_http):
    mock_http(_handler_for({"api.lever.co": {"unexpected": "shape"}}))
    board = _board(company="Gizmo Inc", careers_url="https://jobs.lever.co/gizmoinc", ats="lever")
    result = ats.fetch_ats_postings([board], now=NOW)
    assert result.postings == []
    assert result.error == ""


# --- freshness + dedupe -------------------------------------------------------


def test_freshness_window_drops_older_postings_but_keeps_undated_ones(mock_http):
    old = (NOW - timedelta(days=40)).isoformat()
    body = {
        "jobs": [
            {"title": "Old Role", "absolute_url": "https://a.example/1", "updated_at": old},
            {"title": "Undated Role", "absolute_url": "https://b.example/2", "updated_at": ""},
            {"title": "Fresh Role", "absolute_url": "https://c.example/3", "updated_at": NOW.isoformat()},
        ]
    }
    mock_http(_handler_for({"boards-api.greenhouse.io": body}))
    board = _board(ats="greenhouse")
    result = ats.fetch_ats_postings([board], max_posting_age_days=7, now=NOW)
    urls = {p.url for p in result.postings}
    assert urls == {"https://b.example/2", "https://c.example/3"}


def test_dedupe_by_url_across_companies(mock_http):
    shared_url = "https://boards.greenhouse.io/widgetco/jobs/1"
    body = {"jobs": [{"title": "Duplicate Role", "absolute_url": shared_url, "updated_at": NOW.isoformat()}]}
    mock_http(_handler_for({"boards-api.greenhouse.io": body}))
    boards = [
        _board(company="Widgetco", careers_url="https://boards.greenhouse.io/widgetco", ats="greenhouse"),
        _board(company="Widgetco Duplicate", careers_url="https://boards.greenhouse.io/widgetco", ats="greenhouse"),
    ]
    result = ats.fetch_ats_postings(boards, now=NOW)
    assert len(result.postings) == 1
    assert result.postings[0].url == shared_url


def test_fetch_never_raises_on_a_totally_broken_client(monkeypatch):
    class ExplodingClient:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    import httpx as httpx_module

    monkeypatch.setattr(httpx_module, "Client", ExplodingClient)
    result = ats.fetch_ats_postings([_board(ats="greenhouse")], now=NOW)
    assert result.postings == []
    assert result.error != ""
