"""Remote Rocketship jobs feed: profile criteria in, posting URLs out.

One POST endpoint, authenticated with a bearer API key the operator saves on
the Job boards page. Documented at https://www.remoterocketship.com/api-docs.

Two properties this module holds to, because the agent's run prompt is built
on top of it:

  - A fetch NEVER raises for the caller's benefit. The config route that calls
    it must keep serving config when Remote Rocketship is down, rate-limiting,
    or rejecting the key. Failures come back as a FeedResult with ``error``
    set, and the caller decides whether to surface it.
  - The API key is passed in by the caller and never logged, echoed, or
    returned in a result. ``FeedResult`` carries postings and an error string
    only.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

from agentconfig.store import JobProfile
from jobfeeds import FeedPosting, FeedResult

__all__ = ["FeedPosting", "FeedResult"]

SOURCE = "remoterocketship"

# Trailing slash is REQUIRED. The docs give this path without one, but the
# host answers that with a 308 to the slashed form, and httpx does not follow
# redirects unless told to — so the un-slashed URL fails every request with
# "Remote Rocketship returned HTTP 308" and never reaches the handler.
API_URL = "https://www.remoterocketship.com/api/openclaw/jobs/"

# The board's own per-request ceiling (docs: "clamped to 1..50"). Asking for
# more is silently clamped, so ask for exactly the ceiling.
ITEMS_PER_PAGE = 50

# Ceiling on postings handed to one agent run, across all profiles. The prompt
# is a finite budget shared with company boards and the composed dork queries;
# a profile matching thousands of jobs must not crowd them out.
MAX_POSTINGS = 60

# The daily cap is 500 requests (UTC). Originally sized for one request per
# enabled profile; pagination can need a second page per profile to clear
# ITEMS_PER_PAGE (50) toward MAX_POSTINGS (60), so the cap is doubled to admit
# that without meaningfully eating into the day's 500-request budget.
MAX_REQUESTS = 16

TIMEOUT_SECONDS = 8.0

# Wall-clock ceiling on a whole fetch, across every profile. This exists
# because of the caller on the other side: the agent asks for the feed as part
# of GET /agent/config, and agent/agent-config.js gives that request a fixed
# socket timeout. Per-request timeouts alone do not bound the total — eight
# slow profiles would blow past it — and a config fetch that times out does not
# cost the feed, it aborts the run. Postings already collected are returned
# when the budget runs out. Raised from 12s to 20s alongside MAX_REQUESTS:
# pagination roughly doubles the requests a fetch can make, so the wall clock
# it is allowed needs the same headroom, while staying well under the agent's
# 30s socket timeout for the whole config fetch.
BUDGET_SECONDS = 20.0

ENV_KEY = "REMOTE_ROCKETSHIP_API_KEY"

# Remote-model strings the Agents page writes into a profile, mapped to the
# feed's three visibility booleans. Anything else — including the empty/None
# default — falls through to remote-only, which is what this board is for.
_REMOTE_MODEL_FLAGS: dict[str, dict[str, bool]] = {
    "remote": {"showRemoteJobs": True, "showHybridJobs": False, "showOnsiteJobs": False},
    "hybrid": {"showRemoteJobs": True, "showHybridJobs": True, "showOnsiteJobs": False},
    "onsite": {"showRemoteJobs": False, "showHybridJobs": False, "showOnsiteJobs": True},
    "on-site": {"showRemoteJobs": False, "showHybridJobs": False, "showOnsiteJobs": True},
}

_DEFAULT_REMOTE_FLAGS = _REMOTE_MODEL_FLAGS["remote"]


def api_key() -> str:
    """The saved Remote Rocketship key, falling back to the environment.

    Same resolution order as every other credential in the app: secrets.enc
    first (when ENCRYPTION_KEY is valid), then the environment.
    """
    import secretstore

    stored = secretstore.get_connection(SOURCE).get("apiKey", "")
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    return os.environ.get(ENV_KEY, "").strip()


def filters_for_profile(
    profile: JobProfile, items_per_page: int = ITEMS_PER_PAGE, page: int = 1
) -> dict:
    """Map one job profile onto the feed's filter object.

    Keywords go to ``keywordFilters`` rather than ``jobTitleFilters``: the
    latter is a closed enum of 207 titles, and a profile's keywords are
    free text the operator typed. The docs say unrecognised values are
    ignored or normalised, so a location that is not one of the board's 245
    known ones costs nothing — it just does not narrow the search.

    Posting age is deliberately NOT expressed here. The API has no date
    filter; ``sortBy: DateAdded`` gives newest-first and the window is applied
    to ``created_at`` after the fact by ``_within_age``.

    ``page`` is 1-based, matching the board's own paging: ``fetch_postings``
    walks pages 1, 2, 3... for a profile until a termination condition stops it.
    """
    filters: dict = {
        "page": page,
        "itemsPerPage": items_per_page,
        "sortBy": "DateAdded",
    }
    filters.update(_REMOTE_MODEL_FLAGS.get((profile.remote_model or "").strip().casefold(), _DEFAULT_REMOTE_FLAGS))

    keywords = [k.strip() for k in profile.keywords if k.strip()]
    if keywords:
        filters["keywordFilters"] = keywords

    excluded = [t.strip() for t in profile.rejected_role_types if t.strip()]
    if excluded:
        filters["excludedKeywordFilters"] = excluded

    locations = [loc.strip() for loc in profile.locations if loc.strip()]
    if locations:
        filters["locationFilters"] = locations

    if profile.salary_floor is not None and profile.salary_floor > 0:
        filters["minSalaryFilter"] = profile.salary_floor
        # A posting that states no salary cannot be judged against the floor
        # here, and dropping it would hide roles the agent could still screen
        # (and negotiate) — the profile's salary rules are applied by the
        # agent against the posting text, not by this filter.
        filters["showJobsWithoutSalaryWithMinSalaryFilter"] = True

    return filters


def _error_message(status: int, body: object) -> str:
    """Human-readable failure line for a non-200, using the board's own message when it sent one."""
    detail = ""
    if isinstance(body, dict) and isinstance(body.get("message"), str):
        detail = body["message"]
    if status == 401:
        return detail or "Remote Rocketship rejected the API key."
    if status == 403:
        return detail or "Remote Rocketship requires an active subscription."
    if status == 429:
        return detail or "Remote Rocketship daily request limit reached."
    return detail or f"Remote Rocketship returned HTTP {status}."


def _within_age(created_at: object, max_posting_age_days: int | None, now: datetime) -> bool:
    """Whether a posting's created_at falls inside the freshness window.

    A posting with no parseable date is KEPT: the agent's own prompt says never
    to reject on an age a board did not state, and silently dropping it here
    would enforce the opposite rule one layer down where nobody can see it.
    Only a whole number of days 1..365 is a window — matching the guard in
    agent/daily-apply.sh — so 0, None, and anything malformed mean no filter.
    """
    if not isinstance(max_posting_age_days, int) or isinstance(max_posting_age_days, bool):
        return True
    if max_posting_age_days < 1 or max_posting_age_days > 365:
        return True
    if not isinstance(created_at, str) or not created_at.strip():
        return True
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed >= now - timedelta(days=max_posting_age_days)


def _posting_from_opening(opening: dict, profile_name: str) -> FeedPosting | None:
    """Map one jobOpenings entry to a FeedPosting, or None when it has no URL.

    A posting with no URL is unusable: the agent cannot open it, screen it, or
    apply to it, and rendering it into the prompt would only invite a guess.
    """
    url = opening.get("url")
    if not isinstance(url, str) or not url.strip():
        return None
    company = opening.get("company")
    company_name = company.get("name", "") if isinstance(company, dict) else ""
    return FeedPosting(
        profile=profile_name,
        source=SOURCE,
        title=str(opening.get("roleTitle") or ""),
        company=str(company_name or ""),
        url=url.strip(),
        employment_type=str(opening.get("employmentType") or ""),
        salary_range=str(opening.get("salaryRange") or ""),
        posted_at=str(opening.get("created_at") or ""),
    )


def _collect_postings(
    openings: list,
    profile_name: str,
    max_posting_age_days: int | None,
    moment: datetime,
    seen_urls: set[str],
    postings: list[FeedPosting],
    cap: int,
) -> int:
    """Map, filter and append one page's openings to ``postings``, stopping at ``cap``.

    ``cap`` is the caller's ceiling on ``len(postings)`` — MAX_POSTINGS for a
    single-profile fetch, or a profile's own share of it (see
    ``_profile_budget_shares``) once more than one profile is being fetched.
    Returns the count added.
    """
    added = 0
    for opening in openings:
        if not isinstance(opening, dict):
            continue
        if not _within_age(opening.get("created_at"), max_posting_age_days, moment):
            continue
        posting = _posting_from_opening(opening, profile_name)
        if posting is None or posting.url in seen_urls:
            continue
        seen_urls.add(posting.url)
        postings.append(posting)
        added += 1
        if len(postings) >= cap:
            break
    return added


def _page_urls(openings: list) -> list[str]:
    """Well-formed URLs present on one page, in order."""
    return [
        opening["url"].strip()
        for opening in openings
        if isinstance(opening, dict) and isinstance(opening.get("url"), str) and opening["url"].strip()
    ]


def _page_is_stalled(openings: list, seen_urls: set[str]) -> bool:
    """True when every well-formed URL on this page is already in ``seen_urls``.

    ``seen_urls`` here is scoped to the CURRENT profile's own earlier pages
    (``_fetch_profile_pages`` passes its local ``profile_urls``, not the
    fetch-wide set) — a page that exactly repeats an EARLIER profile's
    results is cross-profile overlap, not this profile stalling, and must not
    stop it from reaching its own later, genuinely new pages.

    Defensive against a board that ignores the ``page`` filter and keeps
    returning page 1: without this check, an unchanging response paginates
    until only the time or request budget stops it.
    """
    urls = _page_urls(openings)
    return bool(urls) and all(url in seen_urls for url in urls)


def _request_page(
    client, headers: dict, profile: JobProfile, page: int, remaining: float
) -> tuple[list | None, str | None, bool]:
    """POST one page for a profile. Returns (openings, error, stop_all).

    ``openings`` is the page's list on success, ``None`` otherwise. ``stop_all``
    means the failure is about the key, the account, or the transport — none of
    which another page or profile can do anything about.
    """
    import httpx

    body = {"filters": filters_for_profile(profile, page=page), "includeJobDescription": False}
    try:
        # Never let one request outlive the remaining budget: the per-request
        # timeout is a ceiling, not the bound that matters to the caller.
        response = client.post(
            API_URL, headers=headers, json=body, timeout=min(TIMEOUT_SECONDS, remaining)
        )
    except httpx.HTTPError as exc:
        return None, f"Could not reach Remote Rocketship: {type(exc).__name__}.", True
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if response.status_code != 200:
        # 401/403/429 are decisions about the key or the account, not about
        # this profile — retrying with the next page or profile burns quota
        # to be told the same thing.
        return None, _error_message(response.status_code, payload), response.status_code in (401, 403, 429)
    openings = payload.get("jobOpenings") if isinstance(payload, dict) else None
    if not isinstance(openings, list):
        return None, "Remote Rocketship returned an unexpected response shape.", False
    return openings, None, False


def _profile_budget_shares(remaining_profiles: int, remaining_requests: int, remaining_postings: int) -> tuple[int, int]:
    """Even split of what is LEFT of the fetch-wide budget across the profiles
    still to be fetched.

    Recomputed by the caller before EACH profile — from the budget remaining,
    not the fetch-wide total — rather than once up front. Without a per-profile
    share at all, one profile whose board has many fresh matches — or whose
    pages are all dropped by the age filter, so it never sees a short page —
    can page through the ENTIRE fetch-wide budget before any later profile is
    ever requested. Recomputing from what remains, instead of dividing the
    fetch-wide total once, RECLAIMS budget an earlier profile did not spend
    (an empty board, or one that stalled early) for the profiles still to
    come, while still guaranteeing every remaining profile at least its own
    even share of what is left before another can consume all of it.
    ``max(1, ...)`` guarantees at least one page even when there are more
    profiles left than requests left. MAX_REQUESTS and MAX_POSTINGS themselves
    remain the fetch's absolute ceilings — this only bounds any single
    profile's share of what remains of them.
    """
    count = remaining_profiles or 1
    return max(1, remaining_requests // count), max(1, remaining_postings // count)


# _fetch_profile_pages can hit the wall-clock budget mid-pagination in two
# different shapes, and they read differently: with more profiles still to
# come, they are genuinely skipped; on the last (or only) profile, nothing was
# skipped — that profile's OWN later pages were simply cut off.
_BUDGET_MESSAGE_PROFILES_SKIPPED = "Remote Rocketship was too slow; some profiles were skipped."
_BUDGET_MESSAGE_PAGINATION_CUT_SHORT = "Remote Rocketship was too slow; later postings were not fetched."


def _fetch_profile_pages(
    client,
    headers: dict,
    profile: JobProfile,
    max_posting_age_days: int | None,
    moment: datetime,
    deadline: float,
    seen_urls: set[str],
    postings: list[FeedPosting],
    errors: list[str],
    requests_made: int,
    max_requests: int,
    max_postings: int,
    more_profiles_remain: bool,
) -> tuple[int, bool]:
    """Fetch successive pages for one profile until a termination condition holds.

    ``max_requests``/``max_postings`` are THIS profile's own share of the
    fetch-wide ceilings (``_profile_budget_shares``), not MAX_REQUESTS or
    MAX_POSTINGS themselves. Stall detection is scoped to ``profile_urls``,
    URLs seen on this profile's OWN earlier pages only, so an earlier
    profile's results already in the fetch-wide ``seen_urls`` cannot make this
    profile's first page look stalled.

    Returns (requests_made, stop_all); ``stop_all`` ends the whole fetch, not
    just this profile, on a budget exhaustion or an account-level failure.
    """
    page = 1
    profile_urls: set[str] = set()
    while requests_made < max_requests and len(postings) < max_postings:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            errors.append(
                _BUDGET_MESSAGE_PROFILES_SKIPPED
                if more_profiles_remain
                else _BUDGET_MESSAGE_PAGINATION_CUT_SHORT
            )
            return requests_made, True
        requests_made += 1
        openings, error, stop = _request_page(client, headers, profile, page, remaining)
        if error is not None:
            errors.append(error)
            return requests_made, stop
        if _page_is_stalled(openings, profile_urls):
            return requests_made, False
        _collect_postings(openings, profile.name, max_posting_age_days, moment, seen_urls, postings, max_postings)
        profile_urls.update(_page_urls(openings))
        if len(openings) < ITEMS_PER_PAGE or len(postings) >= max_postings:
            return requests_made, False
        page += 1
    return requests_made, False


def fetch_postings(
    profiles: list[JobProfile],
    key: str,
    max_posting_age_days: int | None = None,
    now: datetime | None = None,
    deadline: float | None = None,
) -> FeedResult:
    """Pull postings for every enabled, keyword-bearing profile. Never raises.

    Paginates each profile up to ITEMS_PER_PAGE per request until a short
    page, its own share of what remains of MAX_POSTINGS/MAX_REQUESTS
    (``_profile_budget_shares``, recomputed before each profile so a later
    profile RECLAIMS budget an earlier one left unspent), the time budget, a
    non-200, or a stalled page (see ``_page_is_stalled``) stops it. Every
    enabled, keyword-bearing profile is guaranteed at least an even share of
    what remains of the fetch-wide MAX_POSTINGS/MAX_REQUESTS ceilings so one
    profile cannot use up either before a later profile is requested even
    once. Results
    de-duplicated by URL across pages and profiles (first match owns it) and
    capped at MAX_POSTINGS. An empty ``key`` is not an error condition — it
    means the board is configured but not yet authenticated, and the caller
    renders nothing rather than a failure.

    ``deadline`` is an optional shared ``time.monotonic()`` ceiling from a
    caller fanning this fetch out alongside another source (see
    jobfeeds.ats.fetch_ats_postings and api/routes.py's
    ``_fetch_feed_postings``): when given, it is used as-is instead of a
    fresh BUDGET_SECONDS window, so the two fetchers split one wall-clock
    ceiling between them instead of each getting its own.
    """
    if not key.strip():
        return FeedResult()

    eligible = [p for p in profiles if p.enabled and p.keywords]

    deadline = deadline if deadline is not None else time.monotonic() + BUDGET_SECONDS
    moment = now or datetime.now(timezone.utc)
    postings: list[FeedPosting] = []
    seen_urls: set[str] = set()
    errors: list[str] = []
    requests_made = 0

    headers = {
        "Authorization": f"Bearer {key.strip()}",
        "Content-Type": "application/json",
    }

    try:
        import httpx

        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            for index, profile in enumerate(eligible):
                if requests_made >= MAX_REQUESTS or len(postings) >= MAX_POSTINGS:
                    break
                requests_share, postings_share = _profile_budget_shares(
                    len(eligible) - index, MAX_REQUESTS - requests_made, MAX_POSTINGS - len(postings)
                )
                requests_made, stop = _fetch_profile_pages(
                    client, headers, profile, max_posting_age_days, moment, deadline,
                    seen_urls, postings, errors, requests_made,
                    min(MAX_REQUESTS, requests_made + requests_share),
                    min(MAX_POSTINGS, len(postings) + postings_share),
                    index < len(eligible) - 1,
                )
                if stop:
                    break
    except Exception as exc:  # noqa: BLE001 — a feed must never break config
        errors.append(f"Remote Rocketship fetch failed: {type(exc).__name__}.")

    return FeedResult(postings=postings[:MAX_POSTINGS], error=errors[0] if errors else "")


def check_key(key: str) -> tuple[bool, str]:
    """Verify a key with a single one-item request. Returns (ok, detail). Never raises."""
    if not key.strip():
        return False, "No API key saved."

    import httpx

    body = {"filters": {"page": 1, "itemsPerPage": 1}, "includeJobDescription": False}
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = client.post(
                API_URL,
                headers={"Authorization": f"Bearer {key.strip()}", "Content-Type": "application/json"},
                json=body,
            )
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not reach Remote Rocketship: {type(exc).__name__}."
    if response.status_code == 200:
        return True, "Remote Rocketship accepted the key."
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return False, _error_message(response.status_code, payload)
