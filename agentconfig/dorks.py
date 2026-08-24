"""Deterministic Google dork-style search query composer.

Turns a job profile's search-intent fields (keywords, locations, preferred
sources) into Google dork query strings and search URLs — a discovery
channel rendered into the unattended agent's run prompt alongside its
free-form WebSearch behaviour, not a replacement for it.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from agentconfig.store import JobProfile

SOURCE_DOMAINS: dict[str, str] = {
    "ashby": "jobs.ashbyhq.com",
    "greenhouse": "job-boards.greenhouse.io",
    "lever": "jobs.lever.co",
    "personio": "jobs.personio.de",
    "linkedin": "linkedin.com/jobs",
    "workday": "myworkdayjobs.com",
}

DEFAULT_BOARD_DOMAINS: list[str] = [
    "jobs.ashbyhq.com",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "myworkdayjobs.com",
]

MAX_QUERIES = 24


def _site_filter(source: str) -> str | None:
    """Resolve a preferred_sources entry to a site: domain, or None if unrecognised."""
    if "." in source:
        return source
    return SOURCE_DOMAINS.get(source.strip().casefold())


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


def _resolve_sources(profile: JobProfile) -> list[str]:
    """Resolve preferred_sources to site domains, falling back to the default boards."""
    if not profile.preferred_sources:
        return list(DEFAULT_BOARD_DOMAINS)
    resolved = []
    for source in profile.preferred_sources:
        domain = _site_filter(source)
        if domain is not None:
            resolved.append(domain)
    return resolved


def compose_profile_queries(profile: JobProfile) -> list[dict]:
    """Compose one dork query + URL per resolved source for a single profile."""
    keyword_group = _or_group(profile.keywords)
    location_group = _or_group(profile.locations)
    negatives = " ".join(f'-"{t}"' for t in profile.rejected_role_types)

    parts_template = [keyword_group, location_group, negatives]

    results = []
    for domain in _resolve_sources(profile):
        parts = [f"site:{domain}"] + [p for p in parts_template if p]
        query = " ".join(parts)
        url = f"https://www.google.com/search?q={quote_plus(query)}&tbs=qdr:w"
        results.append({
            "profile": profile.name,
            "source": domain,
            "query": query,
            "url": url,
        })
    return results


def compose_queries(profiles: list[JobProfile]) -> list[dict]:
    """Compose dork queries for every enabled, keyword-bearing profile, capped at MAX_QUERIES."""
    results: list[dict] = []
    for profile in profiles:
        if not profile.enabled or not profile.keywords:
            continue
        results.extend(compose_profile_queries(profile))
        if len(results) >= MAX_QUERIES:
            break
    return results[:MAX_QUERIES]
