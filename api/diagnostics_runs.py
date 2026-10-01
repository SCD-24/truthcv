"""Run-record tools for the read-only diagnostics MCP endpoint.

`list_runs` returns per-run summaries; `get_run` returns a bounded detail view
with the two unbounded lists (item errors, discovery coverage) paged. Capping
of text fields here is lossy and silent: a capped value carries no marker.
"""

from __future__ import annotations

import runs.store as _runs_store
from api.diagnostics_paging import _clamp_limit

# Start of the agent's recovery boilerplate, which the harness appends to item
# errors. Must match RECOVERY in agent/harness/builtins/screenAndRecordPosting.ts.
_RECOVERY_PREFIX = "Stop acting on this posting, not the entire run;"

_DETAIL_PAGE_DEFAULT = 20
_DETAIL_PAGE_MAX = 100
_ERROR_ENTRY_MAX_CHARS = 500
_COVERAGE_FIELD_MAX_CHARS = 200
_NOTE_MAX_CHARS = 2000
_STOPPED_REASON_MAX_CHARS = 300


def _coverage_list(r) -> list[dict]:
    """The run's coverage entries, skipping any malformed (non-dict) ones."""
    return [c for c in (r.discovery_coverage or []) if isinstance(c, dict)]


def _run_summary(r) -> dict:
    """Counters and status of one run, without any heavy list or text field."""
    counts: dict = {}
    for entry in _coverage_list(r):
        status = entry.get("status", "")
        counts[status] = counts.get(status, 0) + 1
    return {
        "id": r.id,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "status": r.status,
        "trigger": r.trigger,
        "stopped_reason": (r.stopped_reason or "")[:_STOPPED_REASON_MAX_CHARS],
        "apply_cap": r.apply_cap,
        "postings_seen": r.postings_seen,
        "screenings_recorded": r.screenings_recorded,
        "blocked_count": r.blocked_count,
        "applications_submitted": r.applications_submitted,
        "queued_for_approval": r.queued_for_approval,
        "over_cap_writes": r.over_cap_writes,
        "items_failed": r.items_failed,
        "finish_refused": r.finish_refused,
        "finish_refusals": r.finish_refusals,
        "item_error_count": len(r.item_errors or []),
        "coverage_counts": counts,
    }


def list_runs(limit: int = 0, offset: int = 0) -> dict:
    """One page of run summaries, newest-started first, with the total.

    `limit` is clamped by `_clamp_limit`: <=0 means the default of 20, and
    anything above 200 is capped there. Summaries carry no item errors,
    coverage entries or note; use `get_run` for those.
    """
    records, total = _runs_store.list_page(limit=_clamp_limit(limit), offset=offset)
    return {"total": total, "runs": [_run_summary(r) for r in records]}


def _page(items: list, offset: int, limit: int) -> tuple[list, int, int | None]:
    """Slice `items`: (entries, effective offset, next_offset or None at end)."""
    size = _DETAIL_PAGE_DEFAULT if not limit or limit <= 0 else min(limit, _DETAIL_PAGE_MAX)
    start = max(offset or 0, 0)
    entries = items[start:start + size]
    end = start + len(entries)
    return entries, start, (end if end < len(items) else None)


def _split_recovery(text: str) -> tuple[str, str | None]:
    """Split an error into (head, recovery text or None).

    The head is everything before `_RECOVERY_PREFIX`, whitespace-stripped and
    minus one trailing "." (the sentence end preceding the boilerplate).
    """
    idx = text.find(_RECOVERY_PREFIX)
    if idx < 0:
        return text, None
    head = text[:idx].rstrip()
    if head.endswith("."):
        head = head[:-1]
    return head, text[idx:].strip()


def _error_page(errors: list, offset: int, limit: int) -> tuple[dict, str | None]:
    """Paged, recovery-stripped item errors plus the run's first recovery text.

    The recovery text is taken from the first matching entry across ALL
    errors, not just this page, so every page reports it consistently.
    """
    chunk, start, nxt = _page(errors, offset, limit)
    recovery = next(
        (found for found in (_split_recovery(str(e))[1] for e in errors) if found), None
    )
    entries = [_split_recovery(str(raw))[0][:_ERROR_ENTRY_MAX_CHARS] for raw in chunk]
    page = {"total": len(errors), "offset": start, "entries": entries, "next_offset": nxt}
    return page, recovery


def _coverage_entry(c: dict) -> dict:
    """One coverage entry with free-text fields capped and tier defaulted."""
    cap = _COVERAGE_FIELD_MAX_CHARS
    return {
        "channel": c.get("channel", ""),
        "board": str(c.get("board", ""))[:cap],
        "status": c.get("status", ""),
        "postings_found": c.get("postings_found", 0),
        "reason": str(c.get("reason", ""))[:cap],
        "tier": c.get("tier", ""),
    }


def _coverage_page(coverage: list, status: str, offset: int, limit: int) -> dict:
    """Paged coverage entries, optionally filtered by exact status."""
    if status:
        coverage = [c for c in coverage if c.get("status") == status]
    chunk, start, nxt = _page(coverage, offset, limit)
    return {
        "total": len(coverage),
        "offset": start,
        "entries": [_coverage_entry(c) for c in chunk],
        "next_offset": nxt,
    }


def get_run(
    run_id: str,
    errors_offset: int = 0,
    errors_limit: int = 0,
    coverage_status: str = "",
    coverage_offset: int = 0,
    coverage_limit: int = 0,
) -> dict:
    """Bounded detail for one run, or {} if the id is unknown.

    Summary plus a capped note, phase_refusals, and paged `item_errors` and
    `discovery_coverage`. The agent's recovery boilerplate is stripped from
    each error and shown once as `recovery_instruction`. Capping is lossy and
    silent: text beyond the caps is dropped without a marker.
    """
    r = _runs_store.get(run_id)
    if not r:
        return {}
    out = _run_summary(r)
    note = r.note or ""
    out["note"] = note[:_NOTE_MAX_CHARS]
    out["note_length"] = len(note)
    out["phase_refusals"] = r.phase_refusals
    out["item_errors"], recovery = _error_page(r.item_errors or [], errors_offset, errors_limit)
    if recovery:
        out["recovery_instruction"] = recovery
    out["discovery_coverage"] = _coverage_page(
        _coverage_list(r), coverage_status, coverage_offset, coverage_limit
    )
    return out
