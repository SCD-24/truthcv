"""Arbeitnow jobs feed: an always-on default board, no key required.

Unlike Remote Rocketship, Arbeitnow's job-board API is public — GET, no
auth, no per-operator credential — so this feed is not opt-in per board: it
is an unremovable default (see agentconfig/boards.DEFAULT_BOARD_SOURCES) and
is always fetched alongside Remote Rocketship and the ATS feeds.

Same contract as every other fetcher in this package (see jobfeeds/__init__.py
and jobfeeds/remoterocketship.py): ``fetch_postings`` NEVER raises. Every
failure comes back as a ``FeedResult`` with ``error`` set.

The API has no server-side keyword filter, so every page fetched is matched
against every eligible profile client-side, in this module.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from agentconfig.store import JobProfile
from jobfeeds import FeedPosting, FeedResult
from jobfeeds.remoterocketship import _DEFAULT_REMOTE_FLAGS, _REMOTE_MODEL_FLAGS

__all__ = ["FeedPosting", "FeedResult"]

SOURCE = "arbeitnow"

API_URL = "https://www.arbeitnow.com/api/job-board-api"

TIMEOUT_SECONDS = 8.0

# Wall-clock ceiling on a whole fetch when no shared deadline is given by the
# caller. Mirrors remoterocketship.BUDGET_SECONDS: the config route gives the
# combined feed fetch one shared budget (see api/routes.py's
# ``_fetch_feed_postings``), and this default only applies when this fetcher
# is exercised on its own (e.g. in tests).
BUDGET_SECONDS = 20.0

# The API paginates without stating a total; cap how many pages one fetch
# will walk so a very large board cannot consume the whole time budget.
MAX_PAGES = 5

# Ceiling on postings handed to one agent run, across all profiles — matches
# remoterocketship.MAX_POSTINGS so neither feed can crowd the prompt out.
MAX_POSTINGS = 60

# Remote-model strings the Agents page writes into a profile, reconciled
# against this board's single ``remote`` boolean via remoterocketship's
# _REMOTE_MODEL_FLAGS/_DEFAULT_REMOTE_FLAGS. Arbeitnow has no ``hybrid``
# signal of its own, so a remote posting (remote==True) is kept whenever
# showRemoteJobs is set and an onsite posting (remote==False) is kept
# whenever showOnsiteJobs is set — in practice "hybrid" and unset/unknown
# values both resolve to remote-only, and "onsite"/"on-site" to onsite-only.


def _within_age(created_at: object, max_posting_age_days: int | None, now: datetime) -> bool:
    """Whether a posting's unix-seconds created_at falls inside the freshness window.

    Same semantics as remoterocketship._within_age: a window only applies for
    a whole number of days 1..365, and a posting with an unparseable date is
    kept rather than silently dropped.
    """
    if not isinstance(max_posting_age_days, int) or isinstance(max_posting_age_days, bool):
        return True
    if max_posting_age_days < 1 or max_posting_age_days > 365:
        return True
    if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
        return True
    try:
        posted = datetime.fromtimestamp(created_at, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return True
    return posted >= now - timedelta(days=max_posting_age_days)


def _matches_keywords(job: dict, keywords: list[str]) -> bool:
    """Whether any keyword (casefold substring) appears in the title or tags."""
    title = str(job.get("title") or "").casefold()
    tags = [str(t).casefold() for t in job.get("tags") or [] if isinstance(t, (str, int, float))]
    for keyword in keywords:
        needle = keyword.casefold()
        if needle in title or any(needle in tag for tag in tags):
            return True
    return False


def _matches_remote_model(job: dict, remote_model: str) -> bool:
    """Whether a posting's remote flag satisfies a profile's remote_model."""
    remote = bool(job.get("remote"))
    flags = _REMOTE_MODEL_FLAGS.get((remote_model or "").strip().casefold(), _DEFAULT_REMOTE_FLAGS)
    return flags["showRemoteJobs"] if remote else flags["showOnsiteJobs"]


def _matches_locations(job: dict, locations: list[str]) -> bool:
    """Whether a posting satisfies a profile's location list: a substring
    match on the posting's location, OR a remote posting (which has no fixed
    location to match against)."""
    if not locations:
        return True
    if bool(job.get("remote")):
        return True
    location = str(job.get("location") or "").casefold()
    return any(loc.strip().casefold() in location for loc in locations if loc.strip())


def _matches_rejected_role_types(job: dict, rejected_role_types: list[str]) -> bool:
    """Whether the title contains any keyword the profile rejects."""
    title = str(job.get("title") or "").casefold()
    return any(rejected.strip().casefold() in title for rejected in rejected_role_types if rejected.strip())


def _profile_matches(job: dict, profile: JobProfile) -> bool:
    """Whether one job satisfies one eligible profile's client-side criteria."""
    keywords = [k.strip() for k in profile.keywords if k.strip()]
    if not _matches_keywords(job, keywords):
        return False
    if not _matches_locations(job, [loc for loc in profile.locations if loc.strip()]):
        return False
    if not _matches_remote_model(job, profile.remote_model):
        return False
    if _matches_rejected_role_types(job, profile.rejected_role_types):
        return False
    return True


def _has_job_path(url: str) -> bool:
    """Whether a posting URL has a non-empty path — drops bare homepage URLs
    like "https://www.preiswecker.com/", which Arbeitnow's own ``url`` field
    sometimes carries instead of a job-specific link."""
    from urllib.parse import urlparse

    path = urlparse(url).path
    return path not in ("", "/")


def _posting_from_job(job: dict, profile_name: str) -> FeedPosting | None:
    """Map one Arbeitnow job to a FeedPosting, or None when its URL is unusable."""
    url = job.get("url")
    if not isinstance(url, str) or not url.strip() or not _has_job_path(url.strip()):
        return None
    created_at = job.get("created_at")
    posted_at = ""
    if isinstance(created_at, (int, float)) and not isinstance(created_at, bool):
        try:
            posted_at = datetime.fromtimestamp(created_at, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            posted_at = ""
    job_types = [str(t) for t in job.get("job_types") or [] if isinstance(t, (str, int, float))]
    return FeedPosting(
        profile=profile_name,
        source=SOURCE,
        title=str(job.get("title") or ""),
        company=str(job.get("company_name") or ""),
        url=url.strip(),
        employment_type=", ".join(job_types),
        posted_at=posted_at,
    )


def _collect_page(
    jobs: list,
    profiles: list[JobProfile],
    max_posting_age_days: int | None,
    moment: datetime,
    seen_urls: set[str],
    postings: list[FeedPosting],
) -> None:
    """Match one page's jobs against every eligible profile and append hits.

    Stops appending once MAX_POSTINGS is reached. Dedupe is by URL alone,
    fetch-wide: a job already claimed by an earlier profile (or an earlier
    page) is not re-added for a later profile — matching remoterocketship's
    dedupe-by-URL semantics, first match owns it.
    """
    for job in jobs:
        if not isinstance(job, dict):
            continue
        if len(postings) >= MAX_POSTINGS:
            return
        if not _within_age(job.get("created_at"), max_posting_age_days, moment):
            continue
        for profile in profiles:
            if not _profile_matches(job, profile):
                continue
            posting = _posting_from_job(job, profile.name)
            if posting is None:
                break
            if posting.url in seen_urls:
                break
            seen_urls.add(posting.url)
            postings.append(posting)
            if len(postings) >= MAX_POSTINGS:
                return
            break


def _fetch_page(client, page: int, remaining: float) -> tuple[list | None, bool, str | None]:
    """GET one page. Returns (data, has_next, error); data is None on failure."""
    import httpx

    try:
        response = client.get(
            API_URL, params={"page": page}, timeout=min(TIMEOUT_SECONDS, remaining)
        )
    except httpx.HTTPError as exc:
        return None, False, f"Could not reach Arbeitnow: {type(exc).__name__}."
    if response.status_code != 200:
        return None, False, f"Arbeitnow returned HTTP {response.status_code}."
    try:
        payload = response.json()
    except ValueError:
        return None, False, "Arbeitnow returned an unexpected response shape."
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return None, False, "Arbeitnow returned an unexpected response shape."
    links = payload.get("links")
    has_next = isinstance(links, dict) and bool(links.get("next"))
    return payload["data"], has_next, None


def fetch_postings(
    profiles: list[JobProfile],
    max_posting_age_days: int | None = None,
    now: datetime | None = None,
    deadline: float | None = None,
) -> FeedResult:
    """Pull postings from Arbeitnow's public feed, matched against every
    enabled, keyword-bearing profile client-side. Never raises.

    Pages are fetched ONCE — not once per profile, since the API has no
    server-side filter to vary — up to MAX_PAGES, stopping early on an empty
    page, a missing/null ``links.next``, the deadline, or an error. Each
    profile is matched against every job on every page fetched. Results are
    de-duplicated per profile by URL and capped fetch-wide at MAX_POSTINGS.

    ``deadline`` is an optional shared ``time.monotonic()`` ceiling (see
    remoterocketship.fetch_postings and api/routes.py's
    ``_fetch_feed_postings``): when given, it is used as-is instead of a
    fresh BUDGET_SECONDS window.
    """
    eligible = [p for p in profiles if p.enabled and p.keywords]
    if not eligible:
        return FeedResult()

    deadline = deadline if deadline is not None else time.monotonic() + BUDGET_SECONDS
    moment = now or datetime.now(timezone.utc)
    postings: list[FeedPosting] = []
    seen_urls: set[str] = set()

    try:
        import httpx

        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            for page in range(1, MAX_PAGES + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or len(postings) >= MAX_POSTINGS:
                    break
                data, has_next, error = _fetch_page(client, page, remaining)
                if error is not None:
                    return FeedResult(postings=postings[:MAX_POSTINGS], error=error)
                if not data:
                    break
                _collect_page(data, eligible, max_posting_age_days, moment, seen_urls, postings)
                if not has_next:
                    break
    except Exception as exc:  # noqa: BLE001 — a feed must never break config
        return FeedResult(postings=postings[:MAX_POSTINGS], error=f"Arbeitnow fetch failed: {type(exc).__name__}.")

    return FeedResult(postings=postings[:MAX_POSTINGS])
