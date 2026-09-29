"""Per-company ATS postings: pull a watched company's jobs straight from its
applicant-tracking-system's public API, keyed off the recorded ``CompanyBoard``.

Where jobfeeds.remoterocketship maps enabled profiles onto one shared board,
this module maps recorded company boards (``companyboards.store.CompanyBoard``)
onto four ATS APIs, dispatching on ``CompanyBoard.ats`` (matched
case-insensitively, since it is free text the agent recorded via
``record_company_board``). It holds the same contract as every other fetcher
in this package (see jobfeeds/__init__.py): a callable that never raises,
returns a ``FeedResult``, and isolates one company's failure from the rest.

All four ATS endpoints are unauthenticated and public — no key, no
secretstore involvement, no per-tenant credential to manage.

``CompanyBoard.careers_url`` is an EMPLOYER careers/apply page (see
``agenttools/tools_boards.py`` and ``companyboards/store.py``), not
necessarily a URL already hosted on the ATS itself — e.g. Google's recorded
careers_url is "https://careers.google.com" even though its ``ats`` is
"Lever". Before deriving a board token/slug/name from it, each builder below
first checks that the URL's HOST is actually one of that ATS's own board
hosts, always case-insensitively (a host's casing carries no meaning). Every
fixed-name URL component compared below — the host, and Greenhouse's literal
"embed" path-segment marker — is likewise compared casefolded, so a
case-sensitive comparison never silently reopens the exact guessing hole this
module exists to close; an actual board token's OWN casing is still
preserved verbatim in the derived id and request URL. A careers_url that is
not an ATS-hosted board URL
(an employer's own domain, or the wrong ATS's host) is SKIPPED — the same as
an unrecognised ``ats`` value — rather than having its first path segment or
hostname label guessed at and used as a board id: guessing risks fetching and
presenting a COMPLETELY UNRELATED company's postings under this company's
name and apply links, if the guessed id happens to exist on that ATS. A
careers_url that IS hosted on the right ATS but yields no derivable token
(e.g. Greenhouse's embed widget with no `for=` parameter) is a distinct case,
surfaced with its own wording — see ``_unhosted_note_kind``.

UNVERIFIED response shapes — this module was written without live network
access, so the following are assumptions from general knowledge of these
platforms, NOT confirmed against a real response. Every parser below is
written defensively (tolerates missing/renamed keys, never assumes a key
exists, never raises) precisely because of this:

  - Greenhouse (``GET boards-api.greenhouse.io/v1/boards/{token}/jobs``):
    assumed to return ``{"jobs": [{"title", "absolute_url", "updated_at",
    ...}]}``. Board token assumed to be the careers URL's first path segment
    (e.g. "acme" from "https://boards.greenhouse.io/acme"), and is only
    derived when the URL's host is boards.greenhouse.io or
    job-boards.greenhouse.io.
  - Lever (``GET api.lever.co/v0/postings/{company}?mode=json``): assumed to
    return a bare JSON *array* of postings, each with ``text``, ``hostedUrl``
    (or ``applyUrl``), ``createdAt`` as epoch milliseconds, and
    ``categories.commitment`` for employment type. Slug assumed to be the
    careers URL's first path segment, derived only when the host is
    jobs.lever.co.
  - Ashby (``GET api.ashbyhq.com/posting-api/job-board/{name}``): assumed to
    return ``{"jobs": [{"title", "jobUrl" (or "applyUrl"), "publishedAt",
    "employmentType", ...}]}``. Board name assumed to be the careers URL's
    first path segment, derived only when the host is jobs.ashbyhq.com.
  - Personio (``GET {company}.jobs.personio.de/xml``): assumed to return an
    XML document with repeated ``<position>`` elements carrying ``<id>``,
    ``<name>``, ``<employmentType>``, ``<createdAt>``, and OPTIONALLY a
    ``<url>`` naming that position's own listing directly. This is the least
    certain of the four: when a position carries no ``<url>``, this module
    reconstructs one as ``https://{slug}.jobs.personio.de/job/{id}`` using
    the SAME derived slug the fetch itself used (never the raw careers_url,
    which may include a path/subpage that does not belong in the
    reconstructed link) — that URL shape is an unverified guess, not a
    documented Personio contract. A position for which no URL can be built
    either way is dropped rather than emitted with a fabricated deep link.
    The subdomain company slug is read from the careers URL's hostname (its
    first label), derived only when the host ends in ".jobs.personio.de".
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from companyboards.store import CompanyBoard
from jobfeeds import FeedPosting, FeedResult
from jobfeeds.remoterocketship import _within_age

__all__ = ["FeedPosting", "FeedResult", "fetch_ats_postings"]

GREENHOUSE = "greenhouse"
LEVER = "lever"
ASHBY = "ashby"
PERSONIO = "personio"

# Every FeedPosting this module builds comes straight from a board's own API,
# never a screen-scrape or a search-engine snippet.
TIER = "api"

TIMEOUT_SECONDS = 8.0

# Wall-clock ceiling on a whole fetch, across every company board. Sized like
# jobfeeds.remoterocketship's own budget since this fetcher is expected to run
# alongside it inside the same config request.
BUDGET_SECONDS = 20.0

# One request per company (no pagination — each of these APIs is assumed to
# answer with a company's whole posting list in one response). The cap bounds
# a watchlist that has grown large, not normal use.
MAX_REQUESTS = 60

# Ceiling on postings handed to one agent run, across all companies. Keeps a
# handful of very large boards from crowding out every other feed's postings
# in the prompt.
MAX_POSTINGS = 300

# Bound on concurrently in-flight board fetches. The one shared httpx.Client
# (thread-safe) lets several hosts' requests overlap instead of queuing one
# after another; kept modest so a large watchlist does not open dozens of
# sockets to different ATS hosts at once.
MAX_WORKERS = 4

# The ATS-hosted board hosts each careers_url must resolve to before this
# module will derive a board id from it. Anything else (an employer's own
# careers/apply domain, or the wrong ATS's host) is not an ATS-hosted board
# URL and is skipped rather than guessed at — see module docstring.
_GREENHOUSE_HOSTS = frozenset({"boards.greenhouse.io", "job-boards.greenhouse.io"})

# Greenhouse also serves an embeddable widget shape,
# "https://boards.greenhouse.io/embed/job_board?for=acme", where the first
# path segment is the literal word "embed" rather than a board token — the
# real token is the `for` query parameter instead. Recognised by exact name
# (compared casefolded, like every other URL component here — see module
# docstring) so a real Greenhouse board happening to be named "embed" (in any
# casing) is never misread as this shape.
_GREENHOUSE_EMBED_SEGMENT = "embed"

_LEVER_HOSTS = frozenset({"jobs.lever.co"})
_ASHBY_HOSTS = frozenset({"jobs.ashbyhq.com"})
_PERSONIO_HOST_SUFFIX = ".jobs.personio.de"


def _url_host(url: str) -> str:
    """``url``'s hostname, casefolded. Empty string when there is none or the URL is malformed."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    return (parsed.hostname or "").casefold()


def _first_path_segment(url: str) -> str:
    """First non-empty path segment of ``url``, e.g. "acme" from
    "https://boards.greenhouse.io/acme/jobs". Empty string when there is none.
    NOT casefolded — unlike the host, a path segment can be a real board token
    whose case matters for the request; callers that need a case-insensitive
    comparison (e.g. against ``_GREENHOUSE_EMBED_SEGMENT``) casefold at the
    comparison site instead of here."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    segments = [segment for segment in parsed.path.split("/") if segment]
    return segments[0] if segments else ""


def _hostname_first_label(url: str) -> str:
    """Leftmost label of ``url``'s hostname, e.g. "acme" from
    "https://acme.jobs.personio.de/xml". Empty string when there is none."""
    host = _url_host(url)
    return host.split(".")[0] if host else ""


def _query_param(url: str, name: str) -> str:
    """First value of query parameter ``name`` in ``url``. Empty string when
    absent or the URL is malformed."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    values = parse_qs(parsed.query).get(name)
    return values[0] if values else ""


def _greenhouse_is_hosted(careers_url: str) -> bool:
    return _url_host(careers_url) in _GREENHOUSE_HOSTS


def _lever_is_hosted(careers_url: str) -> bool:
    return _url_host(careers_url) in _LEVER_HOSTS


def _ashby_is_hosted(careers_url: str) -> bool:
    return _url_host(careers_url) in _ASHBY_HOSTS


def _personio_is_hosted(careers_url: str) -> bool:
    return _url_host(careers_url).endswith(_PERSONIO_HOST_SUFFIX)


def _greenhouse_id(careers_url: str) -> str | None:
    """Board token, but only for a careers_url actually hosted on Greenhouse's
    own board domains — see module docstring. Handles Greenhouse's embeddable
    widget shape (see ``_GREENHOUSE_EMBED_SEGMENT``), where the token is the
    `for` query parameter rather than the first path segment. The URL may be
    hosted on the right domain and still yield no token (bare host, or the
    embed shape with no `for=`); the caller tells that case apart from an
    unhosted URL via ``_greenhouse_is_hosted``."""
    if not _greenhouse_is_hosted(careers_url):
        return None
    segment = _first_path_segment(careers_url)
    if segment.casefold() == _GREENHOUSE_EMBED_SEGMENT:
        return _query_param(careers_url, "for") or None
    return segment or None


def _lever_id(careers_url: str) -> str | None:
    if not _lever_is_hosted(careers_url):
        return None
    return _first_path_segment(careers_url) or None


def _ashby_id(careers_url: str) -> str | None:
    if not _ashby_is_hosted(careers_url):
        return None
    return _first_path_segment(careers_url) or None


def _personio_id(careers_url: str) -> str | None:
    if not _personio_is_hosted(careers_url):
        return None
    return _hostname_first_label(careers_url) or None


def _greenhouse_url(careers_url: str) -> str | None:
    token = _greenhouse_id(careers_url)
    return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs" if token else None


def _lever_url(careers_url: str) -> str | None:
    slug = _lever_id(careers_url)
    return f"https://api.lever.co/v0/postings/{slug}?mode=json" if slug else None


def _ashby_url(careers_url: str) -> str | None:
    name = _ashby_id(careers_url)
    return f"https://api.ashbyhq.com/posting-api/job-board/{name}" if name else None


def _personio_url(careers_url: str) -> str | None:
    slug = _personio_id(careers_url)
    return f"https://{slug}.jobs.personio.de/xml" if slug else None


def _lever_timestamp(raw: object) -> str:
    """Lever's ``createdAt`` is epoch milliseconds; converted to ISO-8601 so
    ``_within_age`` can parse it. Falls back to "" when missing or malformed."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return ""
    try:
        return datetime.fromtimestamp(raw / 1000, tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return ""


def _parse_greenhouse(payload: object, _careers_url: str, company: str, _board_id: str) -> list[FeedPosting]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []
    postings: list[FeedPosting] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        url = job.get("absolute_url")
        if not isinstance(url, str) or not url.strip():
            continue
        postings.append(
            FeedPosting(
                source=GREENHOUSE,
                title=str(job.get("title") or ""),
                company=company,
                url=url.strip(),
                posted_at=str(job.get("updated_at") or ""),
                tier=TIER,
            )
        )
    return postings


def _parse_lever(payload: object, _careers_url: str, company: str, _board_id: str) -> list[FeedPosting]:
    items = payload if isinstance(payload, list) else []
    postings: list[FeedPosting] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("hostedUrl") or item.get("applyUrl")
        if not isinstance(url, str) or not url.strip():
            continue
        categories = item.get("categories")
        commitment = categories.get("commitment") if isinstance(categories, dict) else ""
        postings.append(
            FeedPosting(
                source=LEVER,
                title=str(item.get("text") or ""),
                company=company,
                url=url.strip(),
                employment_type=str(commitment or ""),
                posted_at=_lever_timestamp(item.get("createdAt")),
                tier=TIER,
            )
        )
    return postings


def _parse_ashby(payload: object, _careers_url: str, company: str, _board_id: str) -> list[FeedPosting]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []
    postings: list[FeedPosting] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        url = job.get("jobUrl") or job.get("applyUrl")
        if not isinstance(url, str) or not url.strip():
            continue
        postings.append(
            FeedPosting(
                source=ASHBY,
                title=str(job.get("title") or ""),
                company=company,
                url=url.strip(),
                employment_type=str(job.get("employmentType") or ""),
                posted_at=str(job.get("publishedAt") or ""),
                tier=TIER,
            )
        )
    return postings


def _personio_position_url(position: ET.Element, slug: str, job_id: str) -> str:
    """A position's own ``<url>`` when the feed states one, else a
    reconstructed deep link built from the DERIVED ``slug`` — never the raw
    careers_url (see module docstring: this reconstruction is an unverified
    assumption). Empty when neither is available, meaning the caller must
    drop the position rather than emit a fabricated link."""
    feed_url = (position.findtext("url") or "").strip()
    if feed_url:
        return feed_url
    return f"https://{slug}.jobs.personio.de/job/{job_id}" if slug else ""


def _parse_personio(body: object, _careers_url: str, company: str, board_id: str) -> list[FeedPosting]:
    """Parse Personio's XML job feed. Raises ``xml.etree.ElementTree.ParseError``
    on malformed XML — the caller catches it, keeping this fetcher's own
    never-raise contract."""
    if not isinstance(body, str) or not body.strip():
        return []
    root = ET.fromstring(body)
    postings: list[FeedPosting] = []
    for position in root.findall(".//position"):
        job_id = (position.findtext("id") or "").strip()
        if not job_id:
            continue
        url = _personio_position_url(position, board_id, job_id)
        if not url:
            continue
        postings.append(
            FeedPosting(
                source=PERSONIO,
                title=(position.findtext("name") or "").strip(),
                company=company,
                url=url,
                employment_type=(position.findtext("employmentType") or "").strip(),
                posted_at=(position.findtext("createdAt") or "").strip(),
                tier=TIER,
            )
        )
    return postings


@dataclass(frozen=True)
class _AtsHandler:
    """One ATS's dispatch table entry: label, host check, id deriver, URL
    builder, response parser."""

    label: str
    is_hosted: Callable[[str], bool]
    derive_id: Callable[[str], str | None]
    build_url: Callable[[str], str | None]
    parse: Callable[[object, str, str, str], list[FeedPosting]]
    is_xml: bool = False


_HANDLERS: dict[str, _AtsHandler] = {
    GREENHOUSE: _AtsHandler("Greenhouse", _greenhouse_is_hosted, _greenhouse_id, _greenhouse_url, _parse_greenhouse),
    LEVER: _AtsHandler("Lever", _lever_is_hosted, _lever_id, _lever_url, _parse_lever),
    ASHBY: _AtsHandler("Ashby", _ashby_is_hosted, _ashby_id, _ashby_url, _parse_ashby),
    PERSONIO: _AtsHandler(
        "Personio", _personio_is_hosted, _personio_id, _personio_url, _parse_personio, is_xml=True
    ),
}


def _dispatch(board: CompanyBoard) -> tuple[str, _AtsHandler, str] | None:
    """The recognised ats key, handler, and derived request URL for one board,
    or None when it should be skipped: an unrecognised/blank ``ats``, or a
    careers_url that does not yield a usable board id for that ATS (see
    module docstring and ``_unhosted_note_kind``)."""
    ats_key = (board.ats or "").strip().casefold()
    handler = _HANDLERS.get(ats_key)
    if handler is None:
        return None
    url = handler.build_url(board.careers_url)
    if url is None:
        return None
    return ats_key, handler, url


def _unhosted_note_kind(board: CompanyBoard) -> str | None:
    """Which "recognised ats but no feed" case ``board`` hits, or None when it
    hits neither (an unrecognised/blank ``ats``, where no feed was ever
    implied, or an ats+URL combo that DID resolve to a feed).

    Two distinct causes are told apart here because they call for different
    operator action: "unhosted" means careers_url points somewhere other than
    that ATS's own board host (wrong URL entirely); "tokenless" means the URL
    IS on the right host but no board id could be read from it (e.g.
    Greenhouse's embed widget with no `for=` parameter, or a bare host with
    no path at all) — the URL is right, but incomplete.
    """
    handler = _HANDLERS.get((board.ats or "").strip().casefold())
    if handler is None or handler.build_url(board.careers_url) is not None:
        return None
    return "tokenless" if handler.is_hosted(board.careers_url) else "unhosted"


class _DeadlineExceeded(Exception):
    """Internal: raised when reading a streamed ATS response would outlive
    the shared fetch ``deadline`` (see ``_read_within_deadline``)."""


def _read_within_deadline(response, deadline: float) -> bytes:
    """Accumulate a streamed response's body, aborting the instant the
    absolute ``deadline`` (a ``time.monotonic()`` ceiling) passes.

    httpx's own per-request timeout only bounds the GAP between chunks, not
    the read as a whole: a host that trickles one byte just before each
    per-chunk timeout expires can keep a single request alive indefinitely,
    well past a deadline shared with another fetcher fanned out alongside it.
    Checking the absolute deadline after every chunk closes that gap.
    """
    chunks: list[bytes] = []
    for chunk in response.iter_bytes():
        chunks.append(chunk)
        if time.monotonic() >= deadline:
            raise _DeadlineExceeded()
    return b"".join(chunks)


def _parse_response_text(
    handler: _AtsHandler, text: str, board: CompanyBoard, board_id: str
) -> tuple[list[FeedPosting], str | None]:
    """Parse an already-decoded response body per the handler's shape (XML text or JSON)."""
    if handler.is_xml:
        try:
            return handler.parse(text, board.careers_url, board.company, board_id), None
        except ET.ParseError:
            return [], f"{handler.label} returned an unexpected response shape for {board.company}."
    try:
        payload = json.loads(text)
    except ValueError:
        return [], f"{handler.label} returned an unexpected response shape for {board.company}."
    return handler.parse(payload, board.careers_url, board.company, board_id), None


def _fetch_one(
    client, board: CompanyBoard, ats_key: str, url: str, remaining: float, deadline: float
) -> tuple[list[FeedPosting], str | None]:
    """GET and parse one company's postings from the already-derived ``url``. Never raises.

    Streams the response so ``_read_within_deadline`` can enforce the shared
    absolute ``deadline`` chunk-by-chunk, rather than trusting the per-request
    ``timeout`` alone to bound how long this request can stay open (see
    ``_read_within_deadline``).
    """
    import httpx

    handler = _HANDLERS[ats_key]
    board_id = handler.derive_id(board.careers_url) or ""
    try:
        with client.stream("GET", url, timeout=min(TIMEOUT_SECONDS, remaining)) as response:
            if response.status_code != 200:
                return [], f"{handler.label} returned HTTP {response.status_code} for {board.company}."
            body = _read_within_deadline(response, deadline)
            text = body.decode(response.encoding or "utf-8", errors="replace")
    except _DeadlineExceeded:
        return [], f"{handler.label} fetch for {board.company} exceeded the shared feed deadline."
    except httpx.HTTPError as exc:
        return [], f"Could not reach {handler.label} for {board.company}: {type(exc).__name__}."
    return _parse_response_text(handler, text, board, board_id)


# Returned by ``_fetch_worker`` in place of a real error when the shared
# deadline is already gone by the time a worker actually starts — the same
# note the submission loop appends for boards it never got to submitting at
# all. Sharing the exact string lets the merge loop dedupe it down to one
# appearance in ``errors`` regardless of which of the two places produced it.
_DEADLINE_EXCEEDED_NOTE = "ATS fetch was too slow; some companies were skipped."


def _fetch_worker(
    client, board: CompanyBoard, ats_key: str, handler: _AtsHandler, url: str, deadline: float
) -> tuple[CompanyBoard, list[FeedPosting], str | None]:
    """Run ``_fetch_one`` for one board on a worker thread, pairing its result
    with the board it came from so the caller can merge many concurrent
    workers' results back in submission order. Isolates one worker's own bug
    the same way the caller used to isolate a call it made directly.

    Re-derives ``remaining`` from the absolute ``deadline`` here, at
    execution time, rather than trusting the snapshot the caller had when it
    decided to submit this board: submission returns near-instantly, but a
    queued board can sit behind MAX_WORKERS other in-flight requests for
    seconds before a thread actually picks it up, and by then the deadline
    may already be gone. When it is, this returns without ever calling
    ``_fetch_one`` — see ``_DEADLINE_EXCEEDED_NOTE``.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return board, [], _DEADLINE_EXCEEDED_NOTE
    try:
        fetched, error = _fetch_one(client, board, ats_key, url, remaining, deadline)
    except Exception as exc:  # noqa: BLE001 — isolate one company's bug from the rest
        fetched, error = [], f"{handler.label} fetch failed for {board.company}: {type(exc).__name__}."
    return board, fetched, error


def _collect(
    fetched: list[FeedPosting],
    max_posting_age_days: int | None,
    moment: datetime,
    seen_urls: set[str],
    postings: list[FeedPosting],
) -> None:
    """Filter one company's postings by freshness and URL-dedupe, appending in place."""
    for posting in fetched:
        if not posting.url or posting.url in seen_urls:
            continue
        if not _within_age(posting.posted_at, max_posting_age_days, moment):
            continue
        seen_urls.add(posting.url)
        postings.append(posting)
        if len(postings) >= MAX_POSTINGS:
            return


def _compose_error(skipped_unhosted_boards: int, skipped_tokenless_boards: int, errors: list[str]) -> str:
    """Join the "skipped, not a failure" notes (see ``_unhosted_note_kind``)
    with the first real failure, if any."""
    notes: list[str] = []
    if skipped_unhosted_boards:
        plural = "s" if skipped_unhosted_boards != 1 else ""
        notes.append(
            f"{skipped_unhosted_boards} company board{plural} skipped: "
            "careers_url is not an ATS-hosted board URL."
        )
    if skipped_tokenless_boards:
        plural = "s" if skipped_tokenless_boards != 1 else ""
        notes.append(
            f"{skipped_tokenless_boards} company board{plural} skipped: "
            "careers_url is ATS-hosted but no board token could be derived from it."
        )
    if errors:
        notes.append(errors[0])
    return " ".join(notes)


def fetch_ats_postings(
    boards: list[CompanyBoard],
    max_posting_age_days: int | None = None,
    now: datetime | None = None,
    deadline: float | None = None,
) -> FeedResult:
    """Pull postings for every recorded company board with a recognised ATS. Never raises.

    Dispatches on ``CompanyBoard.ats``, matched case-insensitively. A board
    whose ``ats`` is blank or unrecognised is silently skipped (nothing was
    ever expected there). A board whose ``ats`` IS recognised but whose
    ``careers_url`` yields no usable board id — either because the URL is not
    that ATS's own board host, or because it is but no token/slug/name can be
    read from it (see ``_unhosted_note_kind``) — is also skipped rather than
    guessed at, but both cases are counted and surfaced in ``error`` (a note,
    not a failure — see ``_compose_error``) since the operator recorded a
    board expecting a feed. One company's failure (bad URL, non-200,
    malformed body, or exceeding the shared deadline) is recorded as an error
    and does not stop the others. Results are de-duplicated by URL and capped
    at MAX_POSTINGS.

    ``deadline`` is an optional shared ``time.monotonic()`` ceiling from a
    caller fanning this fetch out alongside another source (see
    jobfeeds.remoterocketship.fetch_postings and api/routes.py's
    ``_fetch_feed_postings``): when given, it is used as-is instead of a
    fresh BUDGET_SECONDS window, so the two fetchers split one wall-clock
    ceiling between them instead of each getting its own. Each request is
    also individually held to this same absolute ceiling while streaming its
    body (see ``_read_within_deadline``), so one slow-trickling host cannot
    outlive it.

    Deciding WHICH boards get fetched at all — dispatch/skip counting, the
    MAX_REQUESTS cap, and the shared deadline check — stays serial, so it can
    stop submitting further work the instant either limit is hit without
    needing results back from anything already in flight. The requests
    actually decided on are then fanned out across a small worker thread pool
    (MAX_WORKERS) sharing this one ``httpx.Client`` (thread-safe), so a slow
    host's wait overlaps with the others' instead of queuing behind it. A
    board that clears the submission-time deadline check can still find the
    deadline gone by the time a worker actually gets to it — submitting
    returns near-instantly, but a queued board can sit behind MAX_WORKERS
    others in flight for seconds — so ``_fetch_worker`` re-checks the same
    absolute deadline right before it would call ``_fetch_one`` (see
    ``_DEADLINE_EXCEEDED_NOTE``). Results are then merged back serially, IN
    SUBMISSION ORDER, through ``_collect`` and ``errors`` — so the
    MAX_POSTINGS cap, URL dedupe, and error ordering all stay exactly as
    deterministic as the fully serial version, regardless of which host
    happens to answer first. (The len(postings) >= MAX_POSTINGS submission
    short-circuit the serial version had is gone — with fetches in flight
    concurrently there is no "postings so far" to check before submitting —
    but MAX_POSTINGS is still enforced at merge time, so the returned
    postings are identical to the serial version's either way. The
    aggregated ``error`` note is not always identical, though: a board whose
    worker finds the deadline already gone by execution time contributes the
    same "too slow" note the serial version only ever produced for boards it
    never reached at all, so that note can now appear in runs the serial
    version would have finished cleanly.)
    """
    deadline = deadline if deadline is not None else time.monotonic() + BUDGET_SECONDS
    moment = now or datetime.now(timezone.utc)
    postings: list[FeedPosting] = []
    seen_urls: set[str] = set()
    errors: list[str] = []
    requests_made = 0
    skipped_unhosted_boards = 0
    skipped_tokenless_boards = 0
    deadline_note_added = False

    try:
        import httpx

        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                submissions: list[Future] = []
                for board in boards:
                    dispatch = _dispatch(board)
                    if dispatch is None:
                        note_kind = _unhosted_note_kind(board)
                        if note_kind == "unhosted":
                            skipped_unhosted_boards += 1
                        elif note_kind == "tokenless":
                            skipped_tokenless_boards += 1
                        continue
                    ats_key, handler, url = dispatch
                    if requests_made >= MAX_REQUESTS:
                        break
                    if deadline - time.monotonic() <= 0:
                        if not deadline_note_added:
                            errors.append(_DEADLINE_EXCEEDED_NOTE)
                            deadline_note_added = True
                        break
                    requests_made += 1
                    submissions.append(
                        executor.submit(_fetch_worker, client, board, ats_key, handler, url, deadline)
                    )

                for future in submissions:
                    _board, fetched, error = future.result()
                    if error == _DEADLINE_EXCEEDED_NOTE:
                        if not deadline_note_added:
                            errors.append(error)
                            deadline_note_added = True
                        continue
                    if error is not None:
                        errors.append(error)
                        continue
                    _collect(fetched, max_posting_age_days, moment, seen_urls, postings)
    except Exception as exc:  # noqa: BLE001 — a feed must never break config
        errors.append(f"ATS fetch failed: {type(exc).__name__}.")

    return FeedResult(
        postings=postings[:MAX_POSTINGS],
        error=_compose_error(skipped_unhosted_boards, skipped_tokenless_boards, errors),
    )
