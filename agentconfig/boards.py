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
    "remoterocketship": "remoterocketship.com",
}

# Boards reached through an HTTP API with a saved key instead of a browser
# sign-in. They are configured like any other board and shown in the same
# list, but two things differ and both are load-bearing:
#
#   - Discovery does NOT emit a Google `site:` dork for them. The feed is
#     pulled directly (see jobfeeds/), and a dork would send the agent to the
#     aggregator's own listing pages instead of the postings the API returns.
#   - There is no sign-in URL, so the Job boards page offers an API key field
#     where every other board offers a "Sign in" button.
#
# Their SOURCE_DOMAINS entry exists only so the UI has a domain to label the
# row with; nothing composes a search from it.
API_BOARD_SOURCES: list[str] = ["remoterocketship"]

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


def is_api_source(source: str) -> bool:
    """Check whether source is an API-backed board (key saved, never signed in to).

    Matches the catalog key AND the board's domain, because the "add a board"
    control also accepts a raw domain: an operator who types
    "remoterocketship.com" instead of picking it from the list must get the
    same board, not a Google dork against the aggregator's listing pages and a
    sign-in button for a session that cannot authenticate anything.
    """
    key = source.strip().casefold()
    domains = {SOURCE_DOMAINS[s].casefold() for s in API_BOARD_SOURCES if s in SOURCE_DOMAINS}
    return key in {s.casefold() for s in API_BOARD_SOURCES} or key in domains


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

    Precedence: an API-backed board never has one (it is authenticated with a
    saved key, not a browser session), so it returns "" even if an override was
    somehow stored; then an explicit override wins; else the catalog's known
    sign-in page for that source; else, for a raw domain, "https://" + the
    domain; else "" when nothing is known.
    """
    if is_api_source(source):
        return ""
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
