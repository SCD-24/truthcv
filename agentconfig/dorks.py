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

from agentconfig.boards import DEFAULT_BOARD_DOMAINS, SOURCE_DOMAINS, resolve_domain
from agentconfig.store import JobProfile

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


def _resolve_sources(sources: list[str] | None) -> list[str]:
    """Resolve board sources to site domains, always including the default boards.

    Behaviour change: source selection used to be a per-profile field with an
    empty-list-only fallback to the defaults. It is now global — the caller
    passes the operator's configured board sources (or None), and the four
    default boards are searched on EVERY run regardless of what is
    configured, with the caller's recognised extras following, de-duplicated.
    """
    domains = list(DEFAULT_BOARD_DOMAINS)
    seen = set(domains)
    for source in sources or []:
        domain = resolve_domain(source)
        if domain is not None and domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return domains


def compose_profile_queries(
    profile: JobProfile,
    max_posting_age_days: int | None = None,
    sources: list[str] | None = None,
) -> list[dict]:
    """Compose one dork query + URL per resolved source for a single profile.

    ``max_posting_age_days`` sets the search URL's recency filter; see
    ``recency_param``. ``sources`` is the operator's globally configured job
    board sources; ``None`` means defaults only — see ``_resolve_sources``.
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
    sources: list[str] | None = None,
) -> list[dict]:
    """Compose dork queries for every enabled, keyword-bearing profile, capped at MAX_QUERIES.

    ``sources`` is the operator's globally configured job board sources,
    shared across all profiles; ``None`` means defaults only.
    """
    results: list[dict] = []
    for profile in profiles:
        if not profile.enabled or not profile.keywords:
            continue
        results.extend(compose_profile_queries(profile, max_posting_age_days, sources))
        if len(results) >= MAX_QUERIES:
            break
    return results[:MAX_QUERIES]
