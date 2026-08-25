"""Job board catalog: the single source of truth for known job boards.

Both discovery (agentconfig/dorks.py) and configuration (agentconfig/store.py)
resolve board sources through this module so the domain list, the default
boards, and their sign-in URLs cannot drift apart. This module is a leaf: it
must not import agentconfig.store or agentconfig.dorks, so both of them can
import it without a cycle.
"""

from __future__ import annotations

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

SIGNIN_URLS: dict[str, str] = {
    "linkedin": "https://www.linkedin.com/login",
    "ashby": "https://jobs.ashbyhq.com",
    "greenhouse": "https://job-boards.greenhouse.io",
    "lever": "https://jobs.lever.co",
    "personio": "https://jobs.personio.de",
    "workday": "https://www.myworkdayjobs.com",
}

# The catalog keys whose domains are exactly DEFAULT_BOARD_DOMAINS. These
# boards are ALWAYS searched and cannot be removed by the operator — they are
# unioned into the resolved board list at resolve time, never seeded into
# storage, so they survive a bad PUT or a hand-edited config file.
DEFAULT_BOARD_SOURCES: list[str] = ["ashby", "greenhouse", "lever", "workday"]


def resolve_domain(source: str) -> str | None:
    """Resolve a board source to a site: domain, or None if unrecognised.

    A source containing "." is treated as a domain already and used verbatim;
    otherwise it is looked up case-insensitively in SOURCE_DOMAINS.
    """
    if "." in source:
        return source
    return SOURCE_DOMAINS.get(source.strip().casefold())


def resolve_signin_url(source: str, override: str = "") -> str:
    """Resolve the sign-in URL for a board source.

    Precedence: an explicit override wins; else the catalog's known sign-in
    page for that source; else, for a raw domain, "https://" + the domain;
    else "" when nothing is known.
    """
    if override.strip():
        return override.strip()
    key = source.strip().casefold()
    if key in SIGNIN_URLS:
        return SIGNIN_URLS[key]
    domain = resolve_domain(source)
    return f"https://{domain}" if domain else ""


def is_default_source(source: str) -> bool:
    """Check whether source is one of the always-searched, unremovable default boards."""
    return source.strip().casefold() in {s.casefold() for s in DEFAULT_BOARD_SOURCES}
