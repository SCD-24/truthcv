"""Wire models for agent runs and their URL ledger."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import _Camel


class DiscoveryCoverageModel(_Camel):
    """One board/query's discovery coverage entry within a RunModel. Mirrors
    the dict shape documented on runs.model.RunRecord.discovery_coverage."""

    channel: str = ""
    board: str = ""
    status: str = ""
    postings_found: int = 0
    reason: str = ""
    # Which extraction tier produced the postings: "api", "harvest", "llm",
    # or "" when not applicable / not recorded.
    tier: str = ""


class BoardBreakdownModel(_Camel):
    """Per-source funnel row within a RunModel. The first five counts are None
    for a legacy run (no stored funnel), whose rows are grouped by host."""

    board: str = ""
    channel: str = ""
    postings_seen: int | None = None
    previously_screened: int | None = None
    not_a_posting: int | None = None
    duplicate: int | None = None
    failed: int | None = None
    for_review: int = 0
    rejected: int = 0
    blocked: int = 0


class BoardBreakdownTotalModel(_Camel):
    """Unique-URL totals across all sources of a run's funnel."""

    postings_seen: int = 0
    previously_screened: int = 0
    not_a_posting: int = 0
    duplicate: int = 0
    failed: int = 0
    for_review: int = 0
    rejected: int = 0
    blocked: int = 0


class UrlLedgerSourceModel(_Camel):
    """One source a ledger URL was seen from."""

    source: str = ""
    channel: str = ""


class UrlLedgerEntryModel(_Camel):
    """One URL and the funnel outcome it ended in."""

    url: str = ""
    outcome: str = ""
    detail: str = ""
    sources: list[UrlLedgerSourceModel] = Field(default_factory=list)


class UrlLedgerResponse(_Camel):
    """GET /api/runs/{run_id}/urls: one page of the ledger and the filtered total."""

    entries: list[UrlLedgerEntryModel] = Field(default_factory=list)
    total: int = 0


class RunModel(_Camel):
    """One agent run record — the wire shape for GET /api/runs and
    GET /api/runs/{run_id}. Mirrors runs.model.RunRecord field-for-field."""

    id: str = ""
    started_at: str = ""
    finished_at: str = ""
    status: str = ""
    trigger: str = ""
    apply_cap: int = 0
    postings_seen: int = 0
    screenings_recorded: int = 0
    blocked_count: int = 0
    applications_submitted: int = 0
    queued_for_approval: int = 0
    items_failed: int = 0
    item_errors: list[str] = Field(default_factory=list)
    over_cap_writes: int = 0
    stopped_reason: str = ""
    note: str = ""
    discovery_coverage: list[DiscoveryCoverageModel] = Field(default_factory=list)
    board_breakdown: list[BoardBreakdownModel] = Field(default_factory=list)
    # Unique-URL totals of the stored funnel; None for a legacy run without one.
    board_breakdown_total: BoardBreakdownTotalModel | None = None
    # Sources whose funnel row does not add up (postings_seen != sum of outcomes).
    funnel_mismatches: list[str] = Field(default_factory=list)
    # True when the URL ledger hit its cap; the funnel counts stay complete.
    url_ledger_truncated: bool = False


class RunListResponse(_Camel):
    """GET /api/runs: one page of runs, newest first.

    ``total`` is the count across all pages, not this page's length — the
    client needs it to know how many pages exist, and it cannot be derived
    from a capped page. ``limit``/``offset`` are echoed back so a client that
    let the server apply its default knows what it actually got.
    """

    runs: list[RunModel]
    total: int = 0
    limit: int = 0
    offset: int = 0


class RunStopResult(_Camel):
    """POST /api/runs/{run_id}/stop result.

    ``outcome`` is "cancelling" when the supervisor was signalled and will
    close the record itself, or "closed" when the record was orphaned (no
    supervisor was watching it) and has been marked failed/orphaned now.
    ``run`` is the run record's current state at the time of the response.
    """

    outcome: Literal["cancelling", "closed"]
    run: RunModel
