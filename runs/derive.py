"""Derive an agent run's coverage counters and board breakdown from its records.

These counters are DERIVED evidence: they are recomputed on read from the
screening and application records that carry this run's ``run_id``, rather
than being incremented counters that can drift from reality. Drift is exactly
what went wrong before — three of the run record's counters had no writer at
all and were displayed as a confident 0 beside an accurate prose summary.

``postings_seen`` is deliberately NOT derived here and stays agent-reported:
a posting the agent looked at and skipped on cooldown, on dedupe, or because
it was already screened leaves no record behind to count.

board_breakdown_by_run derives a per-board summary of screenings attributed to
each run, grouping them by the job board derived from their URL host.

This module never imports or calls ``screening.store`` / ``applications.store``
itself. It takes already-loaded lists so a caller rendering fifty runs loads
each store once instead of fifty times.
"""

from __future__ import annotations

_ZERO = {
    "screenings_recorded": 0,
    "blocked_count": 0,
    "queued_for_approval": 0,
    "applications_submitted": 0,
}


def _empty_counters() -> dict:
    """Return a fresh zeroed counter dict (never share the module-level one)."""
    return dict(_ZERO)


def _count_screening(counters: dict, screening) -> None:
    """Fold one screening into ``counters`` already known to belong to its run."""
    counters["screenings_recorded"] += 1
    # screening_blocker is "could not READ the posting"; apply_blocker is
    # "could not SUBMIT". They are deliberately distinct in screening/model.py
    # and only the former belongs in blocked_count.
    if getattr(screening, "screening_blocker", ""):
        counters["blocked_count"] += 1
    if getattr(screening, "approval", "") == "pending":
        counters["queued_for_approval"] += 1


def counters_by_run(run_ids, screenings, applications) -> dict:
    """Map each run id to its derived counters in one pass per input list.

    ``run_ids`` may contain empty ids; those map to all zeros and never match
    a record, so the historical corpus (every record written before run
    linkage existed, all with ``run_id == ""``) is attributed to no run.
    """
    wanted = {rid for rid in run_ids if rid}
    result = {rid: _empty_counters() for rid in run_ids}
    for screening in screenings:
        rid = getattr(screening, "run_id", "")
        if rid in wanted:
            _count_screening(result[rid], screening)
    for application in applications:
        rid = getattr(application, "run_id", "")
        if rid in wanted and getattr(application, "submitted", False):
            result[rid]["applications_submitted"] += 1
    return result


def derive_counters(run_id: str, screenings: list, applications: list) -> dict:
    """Return the four derived coverage counters for one run.

    An empty ``run_id`` returns all zeros without scanning: a run with no id
    can own no records, and matching "" against "" would otherwise sweep up
    every unlinked historical record.
    """
    if not run_id:
        return _empty_counters()
    return counters_by_run([run_id], screenings, applications)[run_id]


# Outcome columns of a funnel row, in display order.
_OUTCOME_COLUMNS = (
    "previously_screened",
    "not_a_posting",
    "duplicate",
    "failed",
    "for_review",
    "rejected",
    "blocked",
)
# Columns a legacy (host-grouped) row cannot know: reported as None.
_UNKNOWN_COLUMNS = ("postings_seen", "previously_screened", "not_a_posting", "duplicate", "failed")


def _funnel_rows(record) -> list[dict]:
    """Rows from a run's stored source_funnel, board = source name, sorted by
    postings_seen descending then board ascending."""
    rows = []
    for raw in record.source_funnel:
        row = {"board": raw.get("source", ""), "channel": raw.get("channel", "")}
        row["postings_seen"] = int(raw.get("postings_seen", 0))
        row.update({c: int(raw.get(c, 0)) for c in _OUTCOME_COLUMNS})
        rows.append(row)
    return sorted(rows, key=lambda x: (-x["postings_seen"], x["board"]))


def _host_rows(run_id: str, screenings) -> list[dict]:
    """Legacy rows: this run's screenings grouped by URL host/board. Columns
    that need the agent's funnel report are None; for_review (approval ==
    'pending'), rejected (verdict == 'rejected') and blocked (a truthy
    screening_blocker) are counted from the screenings."""
    from agentconfig.boards import board_for_url

    rows: dict[str, dict] = {}
    seen: dict[str, int] = {}
    for s in screenings:
        if getattr(s, "run_id", "") != run_id:
            continue
        board = board_for_url(getattr(s, "url", ""))
        row = rows.setdefault(board, {
            "board": board, "channel": "",
            **dict.fromkeys(_UNKNOWN_COLUMNS), "for_review": 0, "rejected": 0, "blocked": 0,
        })
        seen[board] = seen.get(board, 0) + 1
        row["for_review"] += getattr(s, "approval", "") == "pending"
        row["rejected"] += getattr(s, "verdict", "") == "rejected"
        row["blocked"] += bool(getattr(s, "screening_blocker", ""))
    # Most screenings first, then board, as the pre-funnel breakdown did.
    return sorted(rows.values(), key=lambda x: (-seen[x["board"]], x["board"]))


def board_breakdown_by_run(records, screenings) -> dict[str, dict]:
    """Per-source breakdown rows and total for each run.

    Args:
        records: RunRecords. A run with a stored ``source_funnel`` gets its
            rows straight from it (board = source, channel, postings_seen and
            the seven outcome columns) and ``funnel_totals`` as its total.
            A legacy run without one falls back to grouping its screenings by
            URL host, with the unknowable columns None and total None.
        screenings: Already-loaded Screening records (not re-read here).

    Returns:
        {run_id: {"rows": [row dicts], "total": dict | None}}.
    """
    result: dict[str, dict] = {}
    for record in records:
        if record.funnel_totals:
            result[record.id] = {"rows": _funnel_rows(record), "total": dict(record.funnel_totals)}
        else:
            rows = _host_rows(record.id, screenings) if record.id else []
            result[record.id] = {"rows": rows, "total": None}
    return result
