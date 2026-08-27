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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from agentconfig.store import JobProfile

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

# One request per enabled profile. The daily cap is 500 requests (UTC), which
# a twice-daily run cannot approach, but an unbounded profile list could.
MAX_REQUESTS = 8

TIMEOUT_SECONDS = 8.0

# Wall-clock ceiling on a whole fetch, across every profile. This exists
# because of the caller on the other side: the agent asks for the feed as part
# of GET /agent/config, and agent/agent-config.js gives that request a fixed
# socket timeout. Per-request timeouts alone do not bound the total — eight
# slow profiles would blow past it — and a config fetch that times out does not
# cost the feed, it aborts the run. Postings already collected are returned
# when the budget runs out.
BUDGET_SECONDS = 12.0

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


@dataclass
class FeedPosting:
    """One posting from the feed, in the shape the agent's run prompt renders."""

    profile: str = ""
    source: str = SOURCE
    title: str = ""
    company: str = ""
    url: str = ""
    employment_type: str = ""
    salary_range: str = ""
    posted_at: str = ""

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "source": self.source,
            "title": self.title,
            "company": self.company,
            "url": self.url,
            "employment_type": self.employment_type,
            "salary_range": self.salary_range,
            "posted_at": self.posted_at,
        }


@dataclass
class FeedResult:
    """Outcome of a fetch: postings, plus a human-readable error when one failed.

    ``error`` being set does not mean ``postings`` is empty — with several
    profiles, one can fail while the others succeed, and dropping the
    successful ones would make a transient failure look like an empty feed.
    """

    postings: list[FeedPosting] = field(default_factory=list)
    error: str = ""


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
    profile: JobProfile, items_per_page: int = ITEMS_PER_PAGE
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
    """
    filters: dict = {
        "page": 1,
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
        title=str(opening.get("roleTitle") or ""),
        company=str(company_name or ""),
        url=url.strip(),
        employment_type=str(opening.get("employmentType") or ""),
        salary_range=str(opening.get("salaryRange") or ""),
        posted_at=str(opening.get("created_at") or ""),
    )


def fetch_postings(
    profiles: list[JobProfile],
    key: str,
    max_posting_age_days: int | None = None,
    now: datetime | None = None,
) -> FeedResult:
    """Pull postings for every enabled, keyword-bearing profile. Never raises.

    One request per profile, capped at MAX_REQUESTS; results de-duplicated by
    URL across profiles (first profile to match a posting owns it) and capped
    at MAX_POSTINGS. An empty ``key`` is not an error condition — it means the
    board is configured but not yet authenticated, and the caller renders
    nothing rather than a failure.
    """
    if not key.strip():
        return FeedResult()

    import httpx

    deadline = time.monotonic() + BUDGET_SECONDS
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
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            for profile in profiles:
                if not profile.enabled or not profile.keywords:
                    continue
                if requests_made >= MAX_REQUESTS or len(postings) >= MAX_POSTINGS:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    errors.append("Remote Rocketship was too slow; some profiles were skipped.")
                    break
                requests_made += 1
                body = {
                    "filters": filters_for_profile(profile),
                    "includeJobDescription": False,
                }
                try:
                    # Never let one request outlive the remaining budget: the
                    # per-request timeout is a ceiling, not the bound that
                    # matters to the caller.
                    response = client.post(
                        API_URL,
                        headers=headers,
                        json=body,
                        timeout=min(TIMEOUT_SECONDS, remaining),
                    )
                except httpx.HTTPError as exc:
                    errors.append(f"Could not reach Remote Rocketship: {type(exc).__name__}.")
                    break
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                if response.status_code != 200:
                    errors.append(_error_message(response.status_code, payload))
                    # 401/403/429 are decisions about the key or the account,
                    # not about this profile — retrying with the next profile
                    # burns quota to be told the same thing.
                    if response.status_code in (401, 403, 429):
                        break
                    continue
                openings = payload.get("jobOpenings") if isinstance(payload, dict) else None
                if not isinstance(openings, list):
                    errors.append("Remote Rocketship returned an unexpected response shape.")
                    continue
                for opening in openings:
                    if not isinstance(opening, dict):
                        continue
                    if not _within_age(opening.get("created_at"), max_posting_age_days, moment):
                        continue
                    posting = _posting_from_opening(opening, profile.name)
                    if posting is None or posting.url in seen_urls:
                        continue
                    seen_urls.add(posting.url)
                    postings.append(posting)
                    if len(postings) >= MAX_POSTINGS:
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
