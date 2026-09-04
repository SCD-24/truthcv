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


def board_breakdown_by_run(run_ids, screenings) -> dict[str, list[dict]]:
    """Derive a per-board summary of screenings for each run in one pass.

    Attributes each screening to a board derived from its URL host. For each
    board, accumulates postings_seen (all screenings for that board), for_review
    (approval == 'pending'), and rejected (verdict == 'rejected').

    Args:
        run_ids: A list of run ids to initialize in the result dict. Empty ids
                 are included but yield empty lists (unlinked screenings are
                 skipped).
        screenings: A list of Screening records. Only those with a run_id in
                    run_ids are attributed to a board.

    Returns:
        A dict mapping each run_id to a list of {board, postings_seen,
        for_review, rejected} dicts, sorted by postings_seen descending, then
        board ascending. A run with no screenings attributed to it has an empty
        list.
    """
    from agentconfig.boards import board_for_url

    wanted = {rid for rid in run_ids if rid}
    result = {rid: {} for rid in run_ids}

    for screening in screenings:
        rid = getattr(screening, "run_id", "")
        if rid not in wanted:
            continue

        url = getattr(screening, "url", "")
        board = board_for_url(url)
        verdict = getattr(screening, "verdict", "")
        approval = getattr(screening, "approval", "")

        if board not in result[rid]:
            result[rid][board] = {
                "board": board,
                "postings_seen": 0,
                "for_review": 0,
                "rejected": 0,
            }

        result[rid][board]["postings_seen"] += 1
        if approval == "pending":
            result[rid][board]["for_review"] += 1
        if verdict == "rejected":
            result[rid][board]["rejected"] += 1

    # Convert dict of dicts to list of dicts, sorted
    return {
        rid: sorted(
            list(breakdown.values()),
            key=lambda x: (-x["postings_seen"], x["board"]),
        )
        for rid, breakdown in result.items()
    }
