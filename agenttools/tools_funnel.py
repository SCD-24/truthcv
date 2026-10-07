"""Per-source run funnel tool for the agent tool surface.

Same module rule as tools_runs.py: every parameter has a default (the MCP
schema is derived from ``inspect.signature``). Unlike the best-effort run
tools, this one validates its input and raises ``ValueError`` on bad data so
the model can correct and resend; a bad report stores nothing.
"""

from __future__ import annotations

import runs.store as _runs_store
import runs.url_ledger as _url_ledger

CHANNELS = ("feed", "direct", "dork")
OUTCOMES = (
    "previously_screened",
    "not_a_posting",
    "duplicate",
    "failed",
    "for_review",
    "rejected",
    "blocked",
)


def _count(value, label: str) -> int:
    """``value`` as a non-negative int, or raise ValueError."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer, got {value!r}.")
    return value


def _clean_counts(raw: dict, label: str) -> dict:
    """postings_seen plus the seven outcome columns, validated (absent = 0)."""
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object.")
    return {k: _count(raw.get(k, 0), f"{label}.{k}") for k in ("postings_seen", *OUTCOMES)}


def _clean_source(raw: dict) -> dict:
    """One validated funnel row {source, channel, counts...}."""
    if not isinstance(raw, dict):
        raise ValueError("each source must be an object.")
    source = raw.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("each source needs a non-empty source name.")
    channel = raw.get("channel")
    if channel not in CHANNELS:
        raise ValueError(f"Unknown channel {channel!r}. Use one of: {', '.join(CHANNELS)}.")
    return {"source": source.strip(), "channel": channel, **_clean_counts(raw, source)}


def _clean_url_source(raw: dict) -> dict:
    """One validated ledger source {source, channel}, or raise ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("each url source must be an object.")
    source = raw.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("each url source needs a non-empty source name.")
    channel = raw.get("channel")
    if channel not in CHANNELS:
        raise ValueError(f"Unknown channel {channel!r} in url sources.")
    return {"source": source, "channel": channel}


def _clean_url(raw: dict) -> dict:
    """One validated ledger entry {url, outcome, detail, sources}."""
    if not isinstance(raw, dict):
        raise ValueError("each url entry must be an object.")
    url = raw.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError("each url entry needs a url.")
    outcome = raw.get("outcome")
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown outcome {outcome!r}. Use one of: {', '.join(OUTCOMES)}.")
    raw_sources = raw.get("sources", [])
    if not isinstance(raw_sources, list):
        raise ValueError("url entry sources must be a list.")
    sources = [_clean_url_source(s) for s in raw_sources]
    return {"url": url, "outcome": outcome, "detail": str(raw.get("detail") or ""), "sources": sources}


def compute_mismatches(rows: list[dict]) -> list[str]:
    """Sources whose postings_seen differs from the sum of the outcome columns."""
    return [
        r["source"]
        for r in rows
        if r["postings_seen"] != sum(r[o] for o in OUTCOMES)
    ]


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
    if not run_id:
        return {"recorded": False}
    rows = [_clean_source(s) for s in sources or []]
    clean_totals = _clean_counts(totals or {}, "totals")
    entries = [_clean_url(u) for u in urls or []]
    mismatches = compute_mismatches(rows)
    if clean_totals["postings_seen"] != sum(clean_totals[o] for o in OUTCOMES):
        mismatches.append("totals")
    if _runs_store.get(run_id) is None:
        return {"recorded": False, "reason": "unknown run"}
    truncated = _url_ledger.write(run_id, entries)
    _runs_store.set_source_funnel(run_id, rows, clean_totals, mismatches, truncated)
    return {"recorded": True, "mismatches": mismatches, "truncated": truncated}
