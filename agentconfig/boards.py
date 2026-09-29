"""Job board catalog: the single source of truth for known job boards.

Both discovery (agentconfig/dorks.py) and configuration (agentconfig/store.py)
resolve board sources through this module so the domain list, the default
boards, and their sign-in URLs cannot drift apart. This module is a leaf: it
must not import agentconfig.store or agentconfig.dorks, so both of them can
import it without a cycle.
"""

from __future__ import annotations

import re

SOURCE_DOMAINS: dict[str, str] = {
    "ashby": "jobs.ashbyhq.com",
    "greenhouse": "job-boards.greenhouse.io",
    "lever": "jobs.lever.co",
    "personio": "jobs.personio.de",
    "linkedin": "linkedin.com/jobs",
    "workday": "myworkdayjobs.com",
    "remoterocketship": "remoterocketship.com",
    "arbeitnow": "arbeitnow.com",
}

# Boards reached through an HTTP API instead of a browser sign-in. Most need
# a saved key (KEYED_API_SOURCES); Arbeitnow's is public and needs none. They
# are configured like any other board and shown in the same list, but two
# things differ and both are load-bearing:
#
#   - Discovery does NOT emit a Google `site:` dork for them. The feed is
#     pulled directly (see jobfeeds/), and a dork would send the agent to the
#     aggregator's own listing pages instead of the postings the API returns.
#   - There is no sign-in URL, so the Job boards page offers an API key field
#     (for KEYED_API_SOURCES) where every other board offers a "Sign in"
#     button.
#
# Their SOURCE_DOMAINS entry exists only so the UI has a domain to label the
# row with; nothing composes a search from it.
API_BOARD_SOURCES: list[str] = ["remoterocketship", "arbeitnow"]

# API-backed sources that need a saved key/credential before their feed can
# run. Arbeitnow's job-board API is public (no auth), so it is API_BOARD_SOURCES
# but NOT here — the key routes (api/routes.py) 404 for it, and its feed is
# always fetched rather than gated on a saved key.
KEYED_API_SOURCES: list[str] = ["remoterocketship"]

# Fixed discovery mode per catalog source: how postings from that board are
# found is a property of the board, not something the operator toggles. Every
# SOURCE_DOMAINS key must appear here so catalog_mode() never falls through to
# a guess. "dork" boards are found via a Google site: search; "feed" is pulled
# directly from the board's own API (see jobfeeds/) and never gets a dork.
CATALOG_MODES: dict[str, str] = {
    "ashby": "dork",
    "greenhouse": "dork",
    "lever": "dork",
    "personio": "dork",
    "linkedin": "dork",
    "workday": "dork",
    "remoterocketship": "feed",
    "arbeitnow": "feed",
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

# The catalog keys whose domains are exactly DEFAULT_BOARD_DOMAINS plus the
# API-backed "arbeitnow" default. These boards are built-in and cannot be
# REMOVED by the operator — they are unioned into the resolved board list at
# resolve time, never seeded into storage, so they survive a bad PUT or a
# hand-edited config file. They CAN be disabled, though (JobBoard.enabled) —
# a disabled default stays listed and re-enableable but drops out of
# discovery. The first four are dork boards; "arbeitnow" is fetched directly
# (see jobfeeds/arbeitnow.py) and never gets a dork, so it deliberately stays
# OUT of DEFAULT_BOARD_DOMAINS.
DEFAULT_BOARD_SOURCES: list[str] = ["ashby", "greenhouse", "lever", "workday", "arbeitnow"]


def api_source_key(source: str) -> str | None:
    """Resolve source to its API_BOARD_SOURCES catalog key, or None if it is not one.

    Matches the catalog key AND the board's domain, because the "add a board"
    control also accepts a raw domain: an operator who types
    "remoterocketship.com" instead of picking it from the list must get the
    same board, not a Google dork against the aggregator's listing pages and a
    sign-in button for a session that cannot authenticate anything.
    """
    key = source.strip().casefold()
    for candidate in API_BOARD_SOURCES:
        if key == candidate.casefold():
            return candidate
        domain = SOURCE_DOMAINS.get(candidate)
        if domain and key == domain.casefold():
            return candidate
    return None


def is_api_source(source: str) -> bool:
    """Check whether source is an API-backed board (key saved or public, never signed in to)."""
    return api_source_key(source) is not None


def requires_key(source: str) -> bool:
    """Check whether source is API-backed AND needs a saved key before its feed can run.

    False for an API board whose feed is public (Arbeitnow) as well as for any
    non-API board; the key routes 404 for both.
    """
    key = api_source_key(source)
    return key in KEYED_API_SOURCES if key is not None else False


def is_custom_source(source: str) -> bool:
    """Check whether source is a custom board — not one of the SOURCE_DOMAINS catalog keys.

    Key match only, case-insensitive; a raw domain that happens to equal a
    catalog board's domain is still treated as custom here (mode selection
    cares only about how the board was added, not what it resolves to).
    """
    return source.strip().casefold() not in SOURCE_DOMAINS


def catalog_mode(source: str) -> str | None:
    """Fixed discovery mode for a catalog source, or None if source is custom.

    Looks source up as a SOURCE_DOMAINS key (case-insensitive) and returns its
    CATALOG_MODES entry. Returns None for any source that is not a catalog
    key, signalling the caller should fall back to the board's own stored
    mode.
    """
    key = source.strip().casefold()
    if key not in SOURCE_DOMAINS:
        return None
    return CATALOG_MODES.get(key, "dork")


def resolve_domain(source: str) -> str | None:
    """Resolve a board source to a bare site: host, or None if unrecognised.

    A catalog key (case-insensitive) resolves to its SOURCE_DOMAINS value
    verbatim. Anything else containing "." is treated as a URL or bare
    domain: scheme, path, query and fragment are stripped, a leading "www."
    is dropped (SOURCE_DOMAINS entries never carry one), and the remaining
    host is returned casefolded. Returns None when no usable host can be
    extracted, rather than a malformed value that would produce a broken
    `site:` dork.
    """
    key = source.strip().casefold()
    if key in SOURCE_DOMAINS:
        return SOURCE_DOMAINS[key]

    if "." not in source:
        return None

    candidate = source.strip()
    for prefix in ("https://", "http://"):
        if candidate.casefold().startswith(prefix):
            candidate = candidate[len(prefix):]
            break
    for sep in ("/", "?", "#"):
        idx = candidate.find(sep)
        if idx != -1:
            candidate = candidate[:idx]
    if candidate.casefold().startswith("www."):
        candidate = candidate[4:]
    candidate = candidate.strip().rstrip(".").casefold()

    if not candidate or "." not in candidate or any(ch.isspace() for ch in candidate):
        return None
    return candidate


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


def search_url_error(v: str) -> str | None:
    """Validate a job board's search_url template; return an error message, or None if valid.

    Empty is fine (no search-results template configured); otherwise it must
    be an http(s) URL carrying a {keywords} placeholder, and after every
    literal "{keywords}"/"{location}" occurrence is removed, no stray "{" or
    "}" may remain (catches malformed/unbalanced placeholder syntax that the
    simple placeholder-name check alone would miss).
    """
    if not v:
        return None
    if not (v.startswith("http://") or v.startswith("https://")):
        return "search_url must start with http:// or https://"
    if "{keywords}" not in v:
        return "search_url must contain a {keywords} placeholder"
    placeholders = set(re.findall(r"\{([^{}]*)\}", v))
    unknown = placeholders - {"keywords", "location"}
    if unknown:
        return f"search_url has unknown placeholder(s): {', '.join(sorted(unknown))}"
    stripped = v.replace("{keywords}", "").replace("{location}", "")
    if "{" in stripped or "}" in stripped:
        return "search_url has an unknown or malformed placeholder"
    return None


def posting_url_pattern_error(v: str) -> str | None:
    """Validate a job board's posting_url_pattern glob; return an error, or None if valid.

    Empty is fine (no pattern configured); otherwise it must start with
    http:// or https://, the host segment (up to the first '/' after the
    scheme) must be non-empty and contain no '*', and the whole value must
    contain no whitespace and no '{' or '}'. '*' elsewhere matches any
    non-whitespace run and is anchored at the start, open at the end.
    """
    if not v:
        return None
    if not (v.startswith("http://") or v.startswith("https://")):
        return "posting_url_pattern must start with http:// or https://"
    scheme_len = len("https://") if v.startswith("https://") else len("http://")
    rest = v[scheme_len:]
    slash_idx = rest.find("/")
    host = rest if slash_idx == -1 else rest[:slash_idx]
    if not host or "*" in host:
        return "posting_url_pattern must have a valid host"
    if any(ch.isspace() for ch in v) or "{" in v or "}" in v:
        return "posting_url_pattern must not contain whitespace, '{', or '}'"
    return None


def is_default_source(source: str) -> bool:
    """Check whether source is one of the built-in, unremovable default boards.

    Built-in and unremovable, not necessarily searched — a default can be
    disabled by the operator (JobBoard.enabled) and still answer True here.
    """
    return source.strip().casefold() in {s.casefold() for s in DEFAULT_BOARD_SOURCES}


def board_for_url(url: str) -> str:
    """Derive a job board catalog key from a URL host.

    Parses the URL, extracts the host, casefolded and with leading 'www.'
    stripped. Matches against SOURCE_DOMAINS: a catalog key whose domain's
    host part (up to the first '/') matches the URL host exactly or as a
    suffix (with a leading dot for suffix matching, e.g., '.example.com')
    wins and is returned. If no catalog match, returns the bare host. If the
    URL is empty or unparseable, returns 'unknown'.

    Args:
        url: A URL string, e.g. 'https://jobs.lever.co/acme' or
             'careers.example.com'.

    Returns:
        A catalog key string if matched (e.g., 'lever', 'linkedin'), a bare
        host if no match (e.g., 'careers.example.com'), or 'unknown' if the
        URL could not be parsed.
    """
    from urllib.parse import urlparse

    if not url or not url.strip():
        return "unknown"

    # Reject URLs with spaces (unparseable)
    if " " in url:
        return "unknown"

    # Parse the URL to extract the netloc (host:port part)
    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
        host = parsed.netloc or parsed.path.split("/")[0]
    except Exception:
        return "unknown"

    if not host:
        return "unknown"

    # Casefold and strip leading 'www.'
    host = host.casefold()
    if host.startswith("www."):
        host = host[4:]

    # Strip port number if present
    if ":" in host:
        host = host.split(":")[0]

    if not host:
        return "unknown"

    # Try to match against SOURCE_DOMAINS
    for key, domain in SOURCE_DOMAINS.items():
        # Extract the host part of the domain (before any '/')
        domain_host = domain.split("/")[0].casefold()
        if domain_host.startswith("www."):
            domain_host = domain_host[4:]

        # Exact match
        if host == domain_host:
            return key

        # Suffix match with a leading dot (e.g., jobs.lever.co matches .lever.co)
        if host.endswith("." + domain_host):
            return key

    # No catalog match; return the bare host
    return host
