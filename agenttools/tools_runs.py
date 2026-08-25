"""Run lifecycle tools for the agent tool surface.

Every function here is best-effort accountability, never a thing that can
fail a run: a run record exists so a partial or crashed run leaves behind an
honest coverage summary, not so a forgetful tool call can abort the agent
mid-application. Every parameter has a default (agenttools/mcp_app.py derives
the JSON schema from ``inspect.signature`` and marks a defaultless parameter
required, which would turn a forgetful model call into a mid-run TypeError),
and every function no-ops on an empty ``run_id`` rather than raising.
"""

from __future__ import annotations

import runs.store as _runs_store


def start_run(run_id: str = "", trigger: str = "scheduled", apply_cap: int = 0) -> dict:
    """Begin a run record. Call once, at the start of a run, with the run id
    given in your prompt. Idempotent: calling this again with the same
    run_id (e.g. because you forgot you already called it) returns the
    existing record rather than resetting its counters.
    """
    if not run_id:
        return {"recorded": False}
    try:
        record = _runs_store.start(run_id, trigger=trigger, apply_cap=apply_cap)
    except Exception:
        return {"recorded": False}
    return {"recorded": True, **record.to_dict()}


def finish_run(
    run_id: str = "",
    status: str = "completed",
    stopped_reason: str = "",
    note: str = "",
) -> dict:
    """Close out a run record. Call this before exiting — including when
    stopping early — with ``stopped_reason`` saying honestly where you
    stopped (e.g. "apply cap reached", "browser session died"). A run that
    ends without this call is indistinguishable from one that crashed.
    """
    if not run_id:
        return {"recorded": False}
    try:
        record = _runs_store.finish(
            run_id, status=status, stopped_reason=stopped_reason, note=note
        )
    except Exception:
        return {"recorded": False}
    if record is None:
        return {"recorded": False}
    return {"recorded": True, **record.to_dict()}


def record_run_note(run_id: str = "", note: str = "") -> dict:
    """Leave a free-text note on the run record, e.g. context that does not
    fit the coverage counters.
    """
    if not run_id or not note:
        return {"recorded": False}
    try:
        record = _runs_store.set_note(run_id, note)
    except Exception:
        return {"recorded": False}
    if record is None:
        return {"recorded": False}
    return {"recorded": True, **record.to_dict()}


def bump_run_counters(run_id: str = "", **counters: int) -> dict:
    """Internal entry point for other tool modules to add to a run's coverage
    counters (postings_seen, screenings_recorded, blocked_count,
    applications_submitted, over_cap_writes). Not registered as an agent-
    facing MCP tool — callers are other tool functions, not the model.
    """
    if not run_id or not counters:
        return {"recorded": False}
    try:
        record = _runs_store.bump(run_id, **counters)
    except Exception:
        return {"recorded": False}
    if record is None:
        return {"recorded": False}
    return {"recorded": True, **record.to_dict()}
