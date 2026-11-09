"""The agent-config update workflow: normalize and merge a PUT body onto the
stored AgentConfig.
"""

from __future__ import annotations

from agentconfig import boards, store as agent_config_store
from agentconfig.salary import clamp_ask as _clamp_ask
from agentconfig.salary import format_ask as _format_ask
from identity.company import company_identity_key
from identity.url import posting_dedupe_key
from screening import store as screening_store

# The optional numeric windows are the exception to exclude_none: for them a
# null is a real value meaning "unset", and dropping it made those fields
# impossible to clear once set. Emptying the box on the Agents page sends
# null, the merge discarded it, and the UI then repainted the old value beside
# a "saved" indicator. They are re-applied explicitly below, still only when
# the client actually sent the key.
_NULLABLE_FIELDS = (
    "cooldown_days",
    "cooldown_days_same_role",
    "cooldown_days_same_company",
    "max_applications_per_run",
    "max_posting_age_days",
)


def update_agent_config(sent: dict) -> agent_config_store.AgentConfig:
    """Merge only the fields present in ``sent`` (already `exclude_unset`d by
    the caller) onto the stored config, and persist the result.

    Profiles are WHOLESALE-REPLACED (not merged) because a null or omitted
    profiles field never reaches the merge dict. job_boards is replaced the
    same way, but first NORMALISED: the response-only keys (domain,
    effective_signin_url, is_default, is_api, key_required, mode_locked) are stripped — they
    are derived, and a stored copy is a second writer that can go stale — and a
    default-source entry is DROPPED only when it carries a blank signin_url
    AND is enabled, so a client echoing back the resolved GET list does not
    bloat storage with the defaults. A default-source entry WITH a
    signin_url, or one the operator has disabled, is kept — both are
    legitimate per-board state with nowhere else to live. ``mode`` IS carried
    through (it is the one board-level field the operator can actually set)
    — dropping it here would silently revert a custom board's mode back to
    "dork" on every save.
    """
    sent = dict(sent)
    if "job_boards" in sent and sent["job_boards"] is not None:
        normalised = []
        for item in sent["job_boards"]:
            source = item.get("source", "")
            signin_url = item.get("signin_url", "")
            mode = item.get("mode", "")
            search_url = item.get("search_url", "")
            enabled = item.get("enabled", True)
            if not isinstance(enabled, bool):
                enabled = True
            posting_url_pattern = item.get("posting_url_pattern", "")
            if (
                boards.is_default_source(source)
                and not signin_url.strip()
                and not posting_url_pattern.strip()
                and enabled
            ):
                continue
            normalised.append({
                "source": source,
                "signin_url": signin_url,
                "mode": mode,
                "search_url": search_url,
                "enabled": enabled,
                "posting_url_pattern": posting_url_pattern,
            })
        sent["job_boards"] = normalised

    merged = agent_config_store.load().to_dict()
    merged.update({k: v for k, v in sent.items() if v is not None})
    for nullable in _NULLABLE_FIELDS:
        if nullable in sent and sent[nullable] is None:
            merged[nullable] = None

    cfg = agent_config_store.AgentConfig.from_dict(merged)
    return agent_config_store.save(cfg)


def load_enabled_profile(profile_name: str):
    """Return the named ENABLED JobProfile, or raise ``ValueError`` naming the enabled ones.

    Evaluating hard requirements against a profile nobody is currently
    searching under would be meaningless, so a disabled or unknown name is
    refused rather than silently matched.

    Public because the screening gate (services/screenings.py) and the agent
    tools both need the same lookup; one definition keeps the match rule and
    the refusal text from drifting apart.
    """
    cfg = agent_config_store.load()
    enabled = [p for p in cfg.profiles if p.enabled]
    needle = profile_name.strip().casefold()
    profile = next((p for p in enabled if p.name.strip().casefold() == needle), None)
    if profile is None:
        names = ", ".join(p.name for p in enabled) or "(none enabled)"
        raise ValueError(
            f"Unknown or disabled profile {profile_name!r}. Enabled profiles: {names}."
        )
    return profile


def recommend_salary(profile_name: str, proposed: int | None = None) -> dict:
    """Recommend a salary ask for a named profile, clamped to its configured band.

    Looks up ``profile_name`` in the configured job profiles and clamps
    ``proposed`` (or the band minimum, if omitted) into
    ``[salary_ask_min, salary_ask_max]`` via ``agentconfig.salary.clamp_ask``.
    Returns a refusal dict if the profile is unknown or has no salary band.

    Lives here so the agent's ``recommend_salary`` tool is a thin adapter and
    the band-lookup and refusal strings have one home next to the config they
    read.
    """
    cfg = agent_config_store.load()
    profile = next((p for p in cfg.profiles if p.name == profile_name), None)
    if profile is None:
        return {"refused": f"Profile not found: {profile_name}"}

    clamped = _clamp_ask(profile, proposed)
    if clamped is None:
        return {"refused": "Profile has no salary band configured"}

    return {
        "amount": clamped,
        "formatted": _format_ask(profile, clamped),
        "band": {"min": profile.salary_ask_min, "max": profile.salary_ask_max},
        # Only a figure the caller actually proposed can be "clamped"; with
        # proposed=None the band minimum is supplied, not adjusted.
        "clamped": proposed is not None and proposed != clamped,
    }


def resolved_job_boards(cfg: agent_config_store.AgentConfig) -> list[dict]:
    """Build the RESOLVED wire list of job boards from an agent config.

    Both GET and PUT responses go through this helper so they cannot drift.
    Iterates ``cfg.resolved_boards()`` (the four defaults, then the operator's
    own boards, each already carrying its EFFECTIVE mode) and for each board
    emits its stored sign-in override (if any), plus the server-resolved
    domain, effective sign-in URL, default marker and mode. ``mode_locked``
    is True for any catalog source — its mode is fixed and not operator-
    editable — and False only for a custom board. The response deliberately
    carries this resolved list rather than the stored one, so the client
    never re-implements the union — and ``is_default`` is what tells the UI
    to withhold a remove button.
    """
    result = []
    for board in cfg.resolved_boards():
        result.append({
            "source": board.source,
            "signin_url": board.signin_url,
            "mode": board.mode,
            "search_url": board.search_url,
            "enabled": board.enabled,
            "posting_url_pattern": board.posting_url_pattern,
            "mode_locked": not boards.is_custom_source(board.source),
            "domain": boards.resolve_domain(board.source) or "",
            "effective_signin_url": boards.resolve_signin_url(board.source, board.signin_url),
            "is_default": boards.is_default_source(board.source),
            "is_api": boards.is_api_source(board.source),
            "key_required": boards.requires_key(board.source),
        })
    return result


def target_company_boards(cfg: agent_config_store.AgentConfig) -> list:
    """Recorded company boards pruned to the current watchlist.

    Matched by identity key (not raw casefold equality) so a legal-entity
    suffix on either side does not exclude a board that is really for a
    target company. Shared by ``build_agent_config``'s ``company_boards``
    response field and ``fetch_feed_postings``'s ATS fan-out, so the two
    never drift onto different prunings of the same store.
    """
    from companyboards import store as board_store

    boards_store_boards = board_store.load()
    board_store.prune(cfg.target_companies)
    target_company_keys = {company_identity_key(name) for name in cfg.target_companies}
    return [
        board for board in boards_store_boards.values()
        if company_identity_key(board.company) in target_company_keys
    ]


def merge_feed_results(*results):
    """Merge several ``FeedResult``s into one, de-duplicated by URL.

    One source failing must not empty out a working one, so every result's
    postings are kept regardless of whether that same result also carries an
    error; the errors themselves are joined so a simultaneous failure of more
    than one source is not silently reduced to just the first.
    """
    from jobfeeds import FeedResult

    postings = []
    seen_urls = set()
    errors = []
    for result in results:
        for posting in result.postings:
            if posting.url and posting.url not in seen_urls:
                seen_urls.add(posting.url)
                postings.append(posting)
        if result.error:
            errors.append(result.error)
    return FeedResult(postings=postings, error=" ".join(errors))


# Combined wall-clock ceiling for the Remote Rocketship, Arbeitnow AND
# per-company ATS fetches TOGETHER, not each source's own separate budget.
# agent/agent-config.js gives the job_config request a fixed 30s socket
# timeout and treats a timeout as a hard failure: it destroys the request and
# calls process.exit(1), discarding the whole config — profiles, feed,
# company boards, and dorks. Each fetcher's own BUDGET_SECONDS (20.0s) was
# sized on the assumption it was the ONLY fetch running; fanning out to three
# independent fetchers with independent budgets can now approach 60s.
# Threading this ONE shared deadline into every caller instead keeps them
# together under a single ceiling: whatever the earlier fetchers spend comes
# out of what the others are given. 25s leaves 5s of headroom under the 30s
# socket timeout for the rest of the config route's own work.
FEED_FETCH_BUDGET_SECONDS = 25.0


def fetch_feed_postings(cfg: agent_config_store.AgentConfig, company_boards: list):
    """Pull postings from Remote Rocketship, Arbeitnow, and every watchlist
    company's own ATS API, whichever apply.

    Fans out across three independent sources and merges them, de-duplicated
    by URL (see ``merge_feed_results``):

    - Remote Rocketship, gated on a resolved board naming it specifically
      (via ``boards.api_source_key``, not the broader ``is_api_source`` —
      Arbeitnow is also API-backed and always present as a default, and must
      not switch Remote Rocketship on) plus its saved key.
    - Arbeitnow, an always-on default board (agentconfig.boards.DEFAULT_BOARD_SOURCES)
      with a public API — gated the same way on a resolved board naming it,
      but never needs a key.
    - Each watchlist company's own ATS API (jobfeeds.ats), gated only on that
      company's ``CompanyBoard.ats`` naming a recognised ATS — no key needed.

    No fetcher ever raises, and this function does not either: a source that
    fails degrades the merged ``error`` rather than emptying the response,
    while the other sources' postings still arrive.

    All three fetches share ONE wall-clock deadline (FEED_FETCH_BUDGET_SECONDS)
    instead of each getting its own — see that constant's comment for why.
    They also run on their own threads instead of one after another, so the
    slowest of the three governs the wall-clock cost of this function rather
    than their sum; the shared deadline still bounds each individually
    exactly as when they ran serially.
    """
    import threading
    import time

    from jobfeeds import arbeitnow, ats, remoterocketship

    deadline = time.monotonic() + FEED_FETCH_BUDGET_SECONDS
    results: dict = {}
    resolved_sources = cfg.resolved_board_sources()

    def _run_remote_rocketship() -> None:
        if any(boards.api_source_key(source) == remoterocketship.SOURCE for source in resolved_sources):
            results["rr"] = remoterocketship.fetch_postings(
                cfg.profiles, remoterocketship.api_key(), cfg.max_posting_age_days, deadline=deadline
            )
        else:
            results["rr"] = remoterocketship.FeedResult()

    def _run_arbeitnow() -> None:
        if any(boards.api_source_key(source) == arbeitnow.SOURCE for source in resolved_sources):
            results["arbeitnow"] = arbeitnow.fetch_postings(
                cfg.profiles, cfg.max_posting_age_days, deadline=deadline
            )
        else:
            results["arbeitnow"] = arbeitnow.FeedResult()

    def _run_ats() -> None:
        results["ats"] = ats.fetch_ats_postings(company_boards, cfg.max_posting_age_days, deadline=deadline)

    threads = [
        threading.Thread(target=_run_remote_rocketship),
        threading.Thread(target=_run_arbeitnow),
        threading.Thread(target=_run_ats),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    return merge_feed_results(results["rr"], results["arbeitnow"], results["ats"])


def _screened_feed(cfg: agent_config_store.AgentConfig, target_boards: list) -> dict:
    """The feed fields of the agent config, minus postings already screened."""
    feed = fetch_feed_postings(cfg, target_boards)
    # Drop postings the ledger already screened, so the agent stops
    # re-screening postings that only come back created:false. An
    # unread-placeholder screening is not in `keys` (screened_dedupe_keys
    # excludes it), so that posting stays in the feed for a real screen.
    # Only postings screened for EVERY enabled profile (or passed/deferred,
    # or profile-less) count as screened; a rejection under one profile
    # must not hide the posting from the others.
    keys = screening_store.screened_dedupe_keys(
        [p.name for p in cfg.profiles if p.enabled]
    )
    kept = [p for p in feed.postings if posting_dedupe_key(p.url) not in keys]
    return {
        "feed_postings": [p.to_dict() for p in kept],
        "feed_error": feed.error,
        "feed_already_screened": len(feed.postings) - len(kept),
    }


def build_agent_config(include_feed: bool) -> dict:
    """Build the agent-config response data: stored config plus resolved boards,
    composed search queries and, on request, the screened API feed.

    Prunes board entries for companies no longer on the target watchlist.
    Lives here so the HTTP handler only validates the dict into its wire
    model; the fan-out and de-duplication have one home next to the config.
    """
    from agentconfig.dorks import compose_direct_boards, compose_queries

    cfg = agent_config_store.load()
    data = cfg.to_dict()

    # Company boards, pruned to the current target watchlist. Shared with the
    # feed fan-out below so the two do not load/prune the store separately.
    target_boards = target_company_boards(cfg)
    data["company_boards"] = [
        {"company": board.company, "careers_url": board.careers_url, "ats": board.ats, "status": board.status, "resolved_at": board.resolved_at}
        for board in target_boards
    ]

    # Populate job_boards with the resolved (defaults-first) list.
    data["job_boards"] = resolved_job_boards(cfg)

    # Populate search_queries in response. The freshness window is applied to
    # the composed URLs here rather than stored on them, so changing the
    # setting takes effect on the next fetch with no stored state to migrate.
    # searched_boards() (not resolved_boards()) is passed so a direct-mode OR
    # operator-disabled board is excluded from the dorks rather than
    # defaulting to "dork"/enabled the way a bare source string would.
    searched = cfg.searched_boards()
    data["search_queries"] = compose_queries(cfg.profiles, cfg.dork_recency, searched)

    # One entry per direct-mode board, for the agent to search on-site.
    data["direct_boards"] = compose_direct_boards(cfg.profiles, searched)

    # Postings from API-backed boards, on request only. fetch_postings never
    # raises, so a Remote Rocketship outage degrades this response to the
    # config it always carried rather than failing the agent's config fetch.
    if include_feed:
        data.update(_screened_feed(cfg, target_boards))

    return data
