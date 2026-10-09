"""Deterministic Google dork-style search query composer.

Turns a job profile's search-intent fields (keywords/title_keywords,
locations) plus the operator's globally configured job boards into Google
dork query strings and search URLs — a discovery channel rendered into the
unattended agent's run prompt alongside its free-form WebSearch behaviour,
not a replacement for it.

Board sources are now GLOBAL rather than per-profile: the four default boards
are searched unless the operator has disabled them, with the operator's
recognised extras added on top of whatever is enabled.

Google's query box has a hard word-limit (~32 words); a query built from a
large keyword list plus locations/remote can blow past it, and a
truncated query silently drops the trailing filters. Discovery therefore
renders TITLES (job-title terms), not free-form keywords, quoted and '|'-grouped as many
per query as fit the word budget, one query per title chunk per board.
Rejected role types are appended as negatives (-"term") best-effort in
whatever room the titles leave; screening (screening/criteria.py
role_type_compatible) still enforces role types.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from itertools import zip_longest
from urllib.parse import quote_plus

from agentconfig.boards import DEFAULT_BOARD_DOMAINS, is_api_source, resolve_domain, resolve_signin_url
from agentconfig.direct_board_presets import preset_for
from agentconfig.store import JobBoard, JobProfile

# Google's search box silently truncates a query beyond roughly this many
# whitespace-separated words; discovery must keep every composed query at
# or under it so location/remote/exclusion terms are never dropped.
MAX_QUERY_WORDS = 32

# Trailing noun of a keyword phrase that marks it as a job title rather than
# a bare skill/technology term, used to detect titles among legacy keywords
# when a profile has no explicit title_keywords (see _dork_titles).
TITLE_NOUNS = frozenset({
    "engineer",
    "developer",
    "analyst",
    "scientist",
    "architect",
    "consultant",
    "manager",
    "lead",
    "specialist",
    "administrator",
    "designer",
    "researcher",
})

# Days counted back from today for each recency letter; an unset or invalid
# letter uses the "w" (past week) offset.
RECENCY_DAYS = {"d": 1, "w": 7, "m": 30, "y": 365}


def recency_operator(dork_recency: str | None, today: date | None = None) -> str:
    """Google ``after:YYYY-MM-DD`` operator for a dork recency letter, or "" for none.

    d/w/m/y count back 1/7/30/365 days from ``today`` (default: today's UTC
    date); "none" yields ""; anything invalid (or None, or a legacy "h")
    uses the "w" offset.
    """
    if dork_recency == "none":
        return ""
    days = RECENCY_DAYS.get(dork_recency, RECENCY_DAYS["w"])
    today = today or datetime.now(timezone.utc).date()
    return f"after:{(today - timedelta(days=days)).isoformat()}"


def _clean_term(term: str) -> str:
    """Strip embedded double quotes and edge whitespace from a term."""
    return (term or "").replace('"', "").strip()


def _quote_term(term: str) -> str:
    """Always wrap the cleaned term in double quotes for an exact-phrase match."""
    return f'"{_clean_term(term)}"'


def _or_group(terms: list[str]) -> str:
    """Build a parenthesized '|'-separated OR-group, or '' if terms is empty.

    Terms are cleaned and empties dropped. Shape ``("A" | "B C")``; a single
    surviving term is quoted but left unparenthesised.
    """
    cleaned = [c for c in (_clean_term(t) for t in terms) if c]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return _quote_term(cleaned[0])
    return "(" + " | ".join(_quote_term(t) for t in cleaned) + ")"


def _remote_group(remote_model: str | None) -> str:
    """Build the OR-group of remote-work terms for a profile's remote_model.

    ``None``, empty, or "on_site" yields "" (no term added — today's query
    is unchanged). "remote" yields terms for remote/fully remote/work from
    home; "hybrid" yields remote-or-hybrid. Any other value is treated like
    "on_site" (no term), since it is not a recognised remote constraint.
    """
    if remote_model == "remote":
        return _or_group(["remote", "fully remote", "work from home"])
    if remote_model == "hybrid":
        return _or_group(["remote", "hybrid"])
    return ""


def _dork_titles(profile: JobProfile) -> list[str]:
    """Job-title terms to search for a profile's dork queries.

    Prefers ``profile.title_keywords`` when set. Otherwise, detects titles
    among the legacy ``keywords`` list: any keyword whose last whitespace-split
    word is a recognised title noun (TITLE_NOUNS), so a bare skill term like
    "Python" is not mistaken for a job title. If none match, falls back to
    the raw keyword list unfiltered, preserving today's behaviour for a
    profile with no title-shaped keywords at all.
    """
    # Strip and drop blanks so a title's word count matches its rendered,
    # quoted form (a stray edge space would render as an extra token).
    explicit = [t.strip() for t in profile.title_keywords if t.strip()]
    if explicit:
        return explicit
    keywords = [kw.strip() for kw in profile.keywords if kw.strip()]
    detected = [kw for kw in keywords if kw.split()[-1].lower() in TITLE_NOUNS]
    return detected or keywords


def _word_count(s: str) -> int:
    """Whitespace-token count of ``s``, matching how Google counts a query's words."""
    return len(s.split())


def _negative_terms(profile: JobProfile) -> list[str]:
    """Rejected role types as ``-"term"`` operators, in order."""
    # Embedded double quotes would break out of the quoted phrase (e.g.
    # `contract" OR "intern`), so strip them before quoting.
    cleaned = [_clean_term(t) for t in profile.rejected_role_types]
    return ["-" + _quote_term(t) for t in cleaned if t]


def _chunk_titles(titles: list[str], budget: int) -> list[list[str]]:
    """Greedily pack titles into chunks whose '|'-joined word cost fits ``budget``.

    A chunk's cost is the sum of its titles' word counts plus one separator
    per join. Every chunk holds at least one title and no title is dropped,
    so an oversized single title gets a chunk of its own.
    """
    chunks: list[list[str]] = []
    current: list[str] = []
    cost = 0
    for title in titles:
        words = _word_count(title)
        if current and cost + 1 + words > budget:
            chunks.append(current)
            current, cost = [], 0
        cost += words + (1 if current else 0)
        current.append(title)
    if current:
        chunks.append(current)
    return chunks


def _resolve_sources(boards: list[JobBoard] | None) -> list[str]:
    """Resolve dork-mode boards to site domains.

    ``boards`` being None is the LEGACY/no-config case and yields the four
    default domains (DEFAULT_BOARD_DOMAINS) unconditionally. Any other value
    (including an empty list) is taken as the full, authoritative set of
    boards to search — typically AgentConfig.searched_boards(), which already
    excludes anything the operator disabled — so an empty list composes no
    queries at all rather than silently falling back to the defaults.

    Takes resolved board records, not bare source strings, so each board's
    EFFECTIVE mode (and its ``enabled`` flag) can be honoured: a board whose
    effective mode is "direct" is skipped here entirely — the agent searches
    it on-site instead (see compose_direct_boards) and it must not also
    consume a `site:` dork slot. A disabled board
    (``enabled`` False) is skipped the same way.

    API-backed boards (agentconfig.boards.API_BOARD_SOURCES) are SKIPPED here
    too. Their postings are pulled from the board's own API in jobfeeds/ and
    handed to the agent as concrete URLs; composing a `site:` dork for one
    would send it to the aggregator's listing pages instead, which is
    strictly worse than the feed it already has.
    """
    if boards is None:
        return list(DEFAULT_BOARD_DOMAINS)
    domains: list[str] = []
    seen: set[str] = set()
    for item in boards:
        # Accept a bare source string too (dork mode implied, enabled
        # implied), so an older caller that has not moved to resolved board
        # records keeps working.
        if isinstance(item, str):
            source, mode, enabled = item, "dork", True
        else:
            source, mode, enabled = item.source, item.mode, getattr(item, "enabled", True)
        if mode == "direct" or is_api_source(source) or not enabled:
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
    profile filter compose_queries applies, now including the profile's
    remote_model so the board's own filter UI can honour the same remote
    constraint — for the agent to use on the board's own search page. A board
    the operator has disabled (``enabled`` False) is skipped entirely, same
    as a dork-mode board.
    """
    profile_entries = [
        {
            "profile": profile.name,
            "keywords": profile.keywords,
            "title_keywords": _dork_titles(profile),
            "locations": profile.locations,
            "rejected_role_types": profile.rejected_role_types,
            "remote_model": profile.remote_model,
        }
        for profile in profiles
        if profile.enabled and (profile.keywords or profile.title_keywords)
    ]
    results: list[dict] = []
    for board in boards or []:
        if getattr(board, "mode", "") != "direct" or not getattr(board, "enabled", True):
            continue
        preset = preset_for(board.source) or {}
        results.append({
            "url": board.source,
            "signin_url": resolve_signin_url(board.source, board.signin_url),
            "search_url": board.search_url or preset.get("search_url", ""),
            "posting_url_pattern": board.posting_url_pattern or preset.get("posting_url_pattern", ""),
            "profiles": profile_entries,
        })
    return results


def compose_profile_queries(
    profile: JobProfile,
    recency: str = "w",
    sources: list[JobBoard | str] | None = None,
    today: date | None = None,
) -> list[dict]:
    """Compose dork queries + URLs per resolved source for a single profile.

    Titles (see ``_dork_titles``), not the full keyword list, drive the
    ``site:`` queries: titles are '|'-grouped and chunked to fit the word
    budget (MAX_QUERY_WORDS) after the fixed site/location/remote/recency
    terms, one query per chunk per source, ordered chunk-major (every source
    for chunk 1, then every source for chunk 2, ...). Rejected role types
    render as negatives (``-"term"``) best-effort in the leftover room only;
    negatives that would overflow are dropped. Screening still enforces
    role types.

    ``recency`` (a DORK_RECENCIES letter) adds an ``after:<date>`` operator
    as the query's last term, counted back from ``today`` (default: today's
    UTC date); see ``recency_operator``. Its word counts toward the budget.
    ``sources`` is the operator's globally configured job
    boards — resolved, enabled JobBoard records (e.g.
    AgentConfig.searched_boards()) or bare source strings, which are treated
    as dork-mode/enabled; ``None`` means the four defaults (legacy), while an
    empty list means no boards at all. A board whose effective mode is
    "direct", or that is disabled, is skipped — see ``_resolve_sources``.
    """
    titles = [c for c in (_clean_term(t) for t in _dork_titles(profile)) if c]
    domains = _resolve_sources(sources)
    if not titles or not domains:
        return []

    location_group = _or_group(profile.locations)
    remote_group = _remote_group(profile.remote_model)
    operator = recency_operator(recency, today)
    negatives = _negative_terms(profile)

    fixed_words = (
        1 + _word_count(location_group) + _word_count(remote_group) + _word_count(operator)
    )
    budget = max(MAX_QUERY_WORDS - fixed_words, 1)

    results = []
    for chunk in _chunk_titles(titles, budget):
        groups = [location_group, remote_group, _or_group(chunk)]
        results.extend(_profile_queries_for_chunk(profile, domains, groups, negatives, operator))
    return results


def _profile_queries_for_chunk(
    profile: JobProfile,
    domains: list[str],
    groups: list[str],
    negatives: list[str],
    operator: str,
) -> list[dict]:
    """Compose one query + URL per domain for a single title chunk.

    ``groups`` are the location/remote/title-group terms; negatives are appended
    in order while the query stays within MAX_QUERY_WORDS, before ``operator``.
    """
    results = []
    for domain in domains:
        base = [f"site:{domain}"] + [g for g in groups if g]
        tail = [operator] if operator else []
        for neg in negatives:
            if _word_count(" ".join(base + [neg] + tail)) > MAX_QUERY_WORDS:
                break
            base.append(neg)
        query = " ".join(base + tail)
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        results.append({
            "profile": profile.name,
            "source": domain,
            "query": query,
            "url": url,
        })
    return results


def _round_robin(query_lists: list[list[dict]]) -> list[dict]:
    """Interleave several query lists one-per-round (A q1, B q1, A q2, ...).

    Nothing is dropped; the interleave just spreads every profile's queries
    evenly so no profile's queries are all bunched at the end.
    """
    results: list[dict] = []
    for round_group in zip_longest(*query_lists):
        for item in round_group:
            if item is None:
                continue
            results.append(item)
    return results


def _dedupe_by_url(entries: list[dict]) -> list[dict]:
    """Drop entries whose ``url`` was already seen; the first occurrence wins.

    Profiles with identical search intent compose identical URLs; the first
    keeps its ``profile`` tag and every survivor gets a ``profiles`` list of
    all profiles that composed that URL. Order of survivors is preserved.
    """
    by_url: dict[str, dict] = {}
    unique: list[dict] = []
    for entry in entries:
        kept = by_url.get(entry["url"])
        if kept is None:
            kept = {**entry, "profiles": [entry["profile"]]}
            by_url[entry["url"]] = kept
            unique.append(kept)
        elif entry["profile"] not in kept["profiles"]:
            kept["profiles"].append(entry["profile"])
    return unique


def compose_queries(
    profiles: list[JobProfile],
    recency: str = "w",
    sources: list[JobBoard | str] | None = None,
    today: date | None = None,
) -> list[dict]:
    """Compose dork queries for every enabled, keyword-bearing profile.

    Every composed query is returned (no cap), interleaved round-robin across
    profiles (see ``_round_robin``), then de-duplicated by URL (see
    ``_dedupe_by_url``) so identical searches from different profiles appear
    once, tagged with the first profile.

    ``sources`` is the operator's globally configured job boards, shared
    across all profiles; ``None`` means the four defaults (legacy), while an
    empty list means no boards at all. See ``compose_profile_queries`` for
    what it accepts and how direct-mode/disabled boards are excluded.
    """
    eligible = [p for p in profiles if p.enabled and (p.keywords or p.title_keywords)]
    per_profile = [
        compose_profile_queries(p, recency, sources, today) for p in eligible
    ]
    return _dedupe_by_url(_round_robin(per_profile))
