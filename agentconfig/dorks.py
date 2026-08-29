"""Deterministic Google dork-style search query composer.

Turns a job profile's search-intent fields (keywords, locations) plus the
operator's globally configured job boards into Google dork query strings and
search URLs — a discovery channel rendered into the unattended agent's run
prompt alongside its free-form WebSearch behaviour, not a replacement for it.

Board sources are now GLOBAL rather than per-profile: the four default boards
are always searched regardless of what is configured, with the operator's
recognised extras added on top.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from agentconfig.boards import DEFAULT_BOARD_DOMAINS, is_api_source, resolve_domain, resolve_signin_url
from agentconfig.store import JobBoard, JobProfile

MAX_QUERIES = 24

DEFAULT_RECENCY = "qdr:w"


def recency_param(max_posting_age_days: int | None) -> str:
    """Google ``tbs`` recency value for a freshness window, or "" for none.
    ...
    """
    if max_posting_age_days is None:
        return DEFAULT_RECENCY
    if max_posting_age_days <= 0:
        return ""
    return f"qdr:d{max_posting_age_days}"


def _quote_term(term: str) -> str:
    """Double-quote a term if it contains whitespace, else leave it bare."""
    return f'"{term}"' if any(ch.isspace() for ch in term) else term


def _or_group(terms: list[str]) -> str:
    """Build a parenthesized OR-group from terms, or '' if terms is empty."""
    if not terms:
        return ""
    if len(terms) == 1:
        return _quote_term(terms[0])
    return "(" + " OR ".join(_quote_term(t) for t in terms) + ")"


def _resolve_sources(boards: list[JobBoard] | None) -> list[str]:
    """Resolve dork-mode boards to site domains, always including the default boards.

    Takes the resolved board records (AgentConfig.resolved_boards()), not bare
    source strings, so each board's EFFECTIVE mode can be honoured: a board
    whose effective mode is "direct" is skipped here entirely — the agent
    searches it on-site instead (see compose_direct_boards) and it must not
    also consume a `site:` dork slot against MAX_QUERIES.

    API-backed boards (agentconfig.boards.API_BOARD_SOURCES) are SKIPPED here
    too. Their postings are pulled from the board's own API in jobfeeds/ and
    handed to the agent as concrete URLs; composing a `site:` dork for one
    would send it to the aggregator's listing pages instead, which is
    strictly worse than the feed it already has.

    ``boards`` being None or empty still yields the four default domains —
    they are baked into DEFAULT_BOARD_DOMAINS directly, independent of any
    board record, so this always returns at least those four.
    """
    domains = list(DEFAULT_BOARD_DOMAINS)
    seen = set(domains)
    for item in boards or []:
        # Accept a bare source string too (dork mode implied), so older
        # callers that have not moved to resolved board records keep working.
        if isinstance(item, str):
            source, mode = item, "dork"
        else:
            source, mode = item.source, item.mode
        if mode == "direct" or is_api_source(source):
            continue
        domain = resolve_domain(source)
        if domain is not None and domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return domains


def compose_direct_boards(
    profiles: list[JobProfile],
    boards: list[JobBoard] | None,
) -> list[dict]:
    """Compose one entry per direct-mode board, for on-site (non-dork) discovery.

    Each entry carries the board's URL EXACTLY as configured (never passed
    through resolve_domain — the agent navigates to it, so it needs the real
    address, not a bare host), its resolved sign-in URL, and the search
    criteria of every enabled, keyword-bearing profile — mirroring the
    profile filter compose_queries applies — for the agent to use on the
    board's own search page.
    """
    profile_entries = [
        {
            "profile": profile.name,
            "keywords": profile.keywords,
            "locations": profile.locations,
            "rejected_role_types": profile.rejected_role_types,
        }
        for profile in profiles
        if profile.enabled and profile.keywords
    ]
    results: list[dict] = []
    for board in boards or []:
        if getattr(board, "mode", "") != "direct":
            continue
        results.append({
            "url": board.source,
            "signin_url": resolve_signin_url(board.source, board.signin_url),
            "profiles": profile_entries,
        })
    return results


def compose_profile_queries(
    profile: JobProfile,
    max_posting_age_days: int | None = None,
    sources: list[JobBoard | str] | None = None,
) -> list[dict]:
    """Compose one dork query + URL per resolved source for a single profile.

    ``max_posting_age_days`` sets the search URL's recency filter; see
    ``recency_param``. ``sources`` is the operator's globally configured job
    boards — resolved JobBoard records (e.g. AgentConfig.resolved_boards())
    or bare source strings, which are treated as dork-mode; ``None`` means
    defaults only. A board whose effective mode is "direct" is skipped — see
    ``_resolve_sources``.
    """
    keyword_group = _or_group(profile.keywords)
    location_group = _or_group(profile.locations)
    negatives = " ".join(f'-"{t}"' for t in profile.rejected_role_types)

    parts_template = [keyword_group, location_group, negatives]

    recency = recency_param(max_posting_age_days)
    results = []
    for domain in _resolve_sources(sources):
        parts = [f"site:{domain}"] + [p for p in parts_template if p]
        query = " ".join(parts)
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        if recency:
            url += f"&tbs={recency}"
        results.append({
            "profile": profile.name,
            "source": domain,
            "query": query,
            "url": url,
        })
    return results


def compose_queries(
    profiles: list[JobProfile],
    max_posting_age_days: int | None = None,
    sources: list[JobBoard | str] | None = None,
) -> list[dict]:
    """Compose dork queries for every enabled, keyword-bearing profile, capped at MAX_QUERIES.

    ``sources`` is the operator's globally configured job boards, shared
    across all profiles; ``None`` means defaults only. See
    ``compose_profile_queries`` for what it accepts and how direct-mode
    boards are excluded.
    """
    results: list[dict] = []
    for profile in profiles:
        if not profile.enabled or not profile.keywords:
            continue
        results.extend(compose_profile_queries(profile, max_posting_age_days, sources))
        if len(results) >= MAX_QUERIES:
            break
    return results[:MAX_QUERIES]
