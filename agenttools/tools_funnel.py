"""Per-source run funnel tool for the agent tool surface.

Same module rule as tools_runs.py: every parameter has a default (the MCP
schema is derived from ``inspect.signature``). Unlike the best-effort run
tools, this one validates its input and raises ``ValueError`` on bad data so
the model can correct and resend; a bad report stores nothing.
"""

from __future__ import annotations

from runs.url_ledger import CHANNELS, OUTCOMES  # noqa: F401 - re-exported
from services.funnel import compute_mismatches  # noqa: F401 - re-exported
from services.funnel import record_source_funnel as _record_source_funnel


def record_source_funnel(
    run_id: str = "",
    sources: list[dict] = [],  # noqa: B006 - never mutated
    totals: dict = {},  # noqa: B006 - never mutated
    urls: list[dict] = [],  # noqa: B006 - never mutated
) -> dict:
    """Record this run's per-source funnel, REPLACING any earlier report.

    sources: rows {source, channel (feed|direct|dork), postings_seen,
    previously_screened, not_a_posting, duplicate, failed, for_review,
    rejected, blocked}. totals: the same counts over UNIQUE URLs. urls: the
    ledger {url, outcome, detail, sources:[{source, channel}]}. Mismatches
    (a source whose postings_seen is not the sum of its outcome columns) are
    computed here, not trusted from the agent.
    """
    return _record_source_funnel(run_id, sources, totals, urls)
