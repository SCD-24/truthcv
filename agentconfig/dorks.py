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
large keyword list plus locations/remote/negatives can blow past it, and a
truncated query silently drops the trailing filters. Discovery therefore
renders TITLES (job-title terms), not free-form keywords, chunked so each
rendered query fits the budget alongside location/remote/negative terms —
see compose_profile_queries.
"""

from __future__ import annotations

from itertools import zip_longest
from urllib.parse import quote_plus

from agentconfig.boards import DEFAULT_BOARD_DOMAINS, is_api_source, resolve_domain, resolve_signin_url
from agentconfig.store import DORK_RECENCIES, JobBoard, JobProfile

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

# Google's past-24-hours filter: an unset window searches only fresh postings.
DEFAULT_RECENCY = "qdr:d"


def recency_param(dork_recency: str | None) -> str:
    """Google ``tbs`` recency value for a dork recency letter, or "" for none.

    One of DORK_RECENCIES: h/d/w/m/y yield ``qdr:<x>``, "none" yields "";
    anything invalid (or None) yields DEFAULT_RECENCY.
    """
    if dork_recency == "none":
        return ""
    if dork_recency in DORK_RECENCIES:
        return f"qdr:{dork_recency}"
    return DEFAULT_RECENCY


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


def _chunk_titles(titles: list[str], budget: int) -> list[list[str]]:
    """Greedily group titles into OR-group chunks that fit ``budget`` words each.

    Cost of a candidate chunk is measured the same way _or_group renders it:
    each title's own word count, plus one word per "OR" joining them. Every
    chunk holds at least one title, even if that title alone exceeds the
    budget, so no title is ever dropped silently.
    """
    chunks: list[list[str]] = []
    current: list[str] = []
    for title in titles:
        candidate = current + [title]
        cost = sum(_word_count(t) for t in candidate) + max(0, len(candidate) - 1)
        if current and cost > budget:
            chunks.append(current)
            current = [title]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _fit_negatives(negative_terms: list[str], fixed_words: int, titles: list[str]) -> list[str]:
    """Drop trailing negative terms until the longest title fits the remaining budget.

    Negatives are the lowest-priority filter: they narrow results but titles
    drive discovery at all, so a negative term is sacrificed before a title
    query is allowed to blow the word budget.
    """
    longest_title_words = max((_word_count(t) for t in titles), default=0)
    terms = list(negative_terms)
    while terms:
        budget = MAX_QUERY_WORDS - fixed_words - _word_count(" ".join(terms))
        if longest_title_words <= budget:
            break
        terms.pop()
    return terms


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
            "locations": profile.locations,
            "rejected_role_types": profile.rejected_role_types,
            "remote_model": profile.remote_model,
        }
        for profile in profiles
        if profile.enabled and profile.keywords
    ]
    results: list[dict] = []
    for board in boards or []:
        if getattr(board, "mode", "") != "direct" or not getattr(board, "enabled", True):
            continue
        results.append({
            "url": board.source,
            "signin_url": resolve_signin_url(board.source, board.signin_url),
            "search_url": board.search_url,
            "posting_url_pattern": board.posting_url_pattern,
            "profiles": profile_entries,
        })
    return results


def compose_profile_queries(
    profile: JobProfile,
    recency: str = "d",
    sources: list[JobBoard | str] | None = None,
) -> list[dict]:
    """Compose dork queries + URLs per resolved source for a single profile.

    Titles (see ``_dork_titles``), not the full keyword list, drive the
    ``site:`` query so it stays inside Google's ~32-word query limit
    (MAX_QUERY_WORDS) alongside the location/remote/negative filters — a
    query that overflows the limit is truncated by Google, silently dropping
    those filters. When titles alone would not fit one query, they are
    chunked (see ``_chunk_titles``) into several queries per source, ordered
    chunk-major (every source for chunk 1, then every source for chunk 2, ...).

    ``recency`` (a DORK_RECENCIES letter) sets the search URL's recency
    filter; see ``recency_param``. ``sources`` is the operator's globally configured job
    boards — resolved, enabled JobBoard records (e.g.
    AgentConfig.searched_boards()) or bare source strings, which are treated
    as dork-mode/enabled; ``None`` means the four defaults (legacy), while an
    empty list means no boards at all. A board whose effective mode is
    "direct", or that is disabled, is skipped — see ``_resolve_sources``.
    """
    titles = _dork_titles(profile)
    domains = _resolve_sources(sources)
    if not titles or not domains:
        return []

    location_group = _or_group(profile.locations)
    remote_group = _remote_group(profile.remote_model)
    negative_terms = [f'-"{t}"' for t in profile.rejected_role_types]

    fixed_words = 1 + _word_count(location_group) + _word_count(remote_group)
    negative_terms = _fit_negatives(negative_terms, fixed_words, titles)
    negatives = " ".join(negative_terms)
    budget = max(MAX_QUERY_WORDS - fixed_words - _word_count(negatives), 1)
    chunks = _chunk_titles(titles, budget)

    recency = recency_param(recency)
    results = []
    for chunk in chunks:
        title_group = _or_group(chunk)
        results.extend(
            _profile_queries_for_chunk(profile, domains, location_group, remote_group, title_group, negatives, recency)
        )
    return results


def _profile_queries_for_chunk(
    profile: JobProfile,
    domains: list[str],
    location_group: str,
    remote_group: str,
    title_group: str,
    negatives: str,
    recency: str,
) -> list[dict]:
    """Compose one query + URL per domain for a single title chunk."""
    results = []
    for domain in domains:
        parts = [f"site:{domain}"] + [
            p for p in (location_group, remote_group, title_group, negatives) if p
        ]
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
    recency: str = "d",
    sources: list[JobBoard | str] | None = None,
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
        compose_profile_queries(p, recency, sources) for p in eligible
    ]
    return _dedupe_by_url(_round_robin(per_profile))
