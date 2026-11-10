"""Run lifecycle tools for the agent tool surface.

Every function here is best-effort accountability, never a thing that can
fail a run: a run record exists so a partial or crashed run leaves behind an
honest coverage summary, not so a forgetful tool call can abort the agent
mid-application. Every parameter has a default (agenttools/mcp_app.py derives
the JSON schema from ``inspect.signature`` and marks a defaultless parameter
required, which would turn a forgetful model call into a mid-run TypeError),
and every function no-ops on an empty ``run_id`` rather than raising.

One deliberate exception: ``finish_run`` raises ``ValueError`` when it is
called on a run whose direct-board or dork-query discovery coverage looks
incomplete, so the model is sent back to finish discovery instead of
silently ending a partial run. See ``services.runs._coverage_shortfall``. When the caller
does not pass ``turns_remaining`` this is the legacy one-shot guard: the
FIRST such call raises and a second always closes the run. When the harness
does pass ``turns_remaining`` the guard is harness-aware instead: it keeps
refusing (up to ``services.runs._MAX_FINISH_REFUSALS`` times) as long as there is enough
run left to act on the refusal, and lets the call through once turns are
nearly exhausted or the refusal cap is reached. ``finish_phase`` offers a
non-terminal way to report the same shortfall mid-run, per channel, without
ever touching run status.
"""

from __future__ import annotations

import truthcv.domain.runs.store as _runs_store
from truthcv.services import runs as _runs_service


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
    turns_remaining: int = -1,
    items_failed: int = 0,
    item_errors: list[str] | None = None,
) -> dict:
    """Close out a run record. Call this before exiting — including when
    stopping early — with ``stopped_reason`` saying honestly where you
    stopped (e.g. "apply cap reached", "browser session died"). A run that
    ends without this call is indistinguishable from one that crashed.

    Raises ValueError, and refuses to close the run, for a 'completed' run
    whose direct-board or dork-query discovery coverage looks incomplete —
    deliberately, to send the model back to finish discovery rather than let
    it stop early unnoticed.

    Pass ``turns_remaining`` (turns left in this run, if your harness tracks
    it) to make the guard harness-aware: it then keeps refusing, up to a
    small cap, for as long as there are enough turns left to act on the
    refusal, and lets the call through once turns are nearly exhausted so a
    real turn-limit stop is never blocked. Omit it (default -1) for the
    legacy one-shot behavior: refuses only the first call, a second always
    succeeds.

    ``items_failed`` is the count of per-item failures that did not fail the
    run (a screening save/screen error, an apply session that did not
    finish); ``item_errors`` is the full error text for each.
    """
    if not run_id:
        return {"recorded": False}
    _runs_service.guard_finish(run_id, status, turns_remaining)
    try:
        record = _runs_store.finish(
            run_id,
            status=status,
            stopped_reason=stopped_reason,
            note=note,
            items_failed=items_failed,
            item_errors=item_errors,
        )
    except Exception:
        return {"recorded": False}
    if record is None:
        return {"recorded": False}
    return {"recorded": True, **record.to_dict()}


def finish_phase(
    run_id: str = "", channel: str = "", note: str = "", turns_remaining: int = -1
) -> dict:
    """Report progress on one discovery channel mid-run, WITHOUT ending the
    run. Unlike finish_run this never changes run status — it exists so the
    model can check in on a channel (or leave a note about it) partway
    through, not just at the very end.

    ``channel`` must be one of feed, direct or dork; any other value returns
    ``{"recorded": False, "error": ...}`` without touching the record.

    Uses the same shortfall check as finish_run's guard, scoped to just this
    channel. When there is a shortfall AND ``turns_remaining`` says there is
    still enough run left to act on it (strictly greater than
    ``_FINISH_GUARD_RESERVE_TURNS``) AND this channel has not already been
    refused ``_MAX_FINISH_REFUSALS`` times, this raises ValueError with
    instructions instead of recording anything — the same shape as
    finish_run's refusal, but per-channel and never terminal. Omitting
    ``turns_remaining`` (default -1) means finish_phase never refuses.

    Otherwise records ``note`` (appended, tagged with the channel) on the run
    and returns ``{"recorded": True, "channel": ..., "shortfall": [...]}`` —
    ``shortfall`` is included even when not refused, e.g. because turns are
    nearly exhausted, so the caller still sees what is short.
    """
    return _runs_service.finish_phase(run_id, channel, note, turns_remaining)


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


def record_postings_seen(run_id: str = "", count: int = 0) -> dict:
    """Report how many job postings you have looked at.

    This is the ONE coverage number that cannot be counted from the records
    you write: a posting you looked at and skipped — on cooldown, as a
    duplicate, or because it was already screened — leaves no record behind.
    Call it as you go with the number of postings you have looked at since
    your last call: it ADDS to the run's total, it does not set it.

    Everything else — screenings recorded, blocked, queued for approval,
    applications submitted — is counted automatically from the records you
    write (provided you pass your run_id on record_screening and
    record_application) and must not be reported here.
    """
    if not run_id or count <= 0:
        return {"recorded": False}
    try:
        record = _runs_service.bump_counters(run_id, postings_seen=count)
    except Exception:
        return {"recorded": False}
    if record is None:
        return {"recorded": False}
    return {"recorded": True, **record.to_dict()}


def record_discovery_coverage(
    run_id: str = "",
    channel: str = "",
    board: str = "",
    status: str = "",
    postings_found: int = 0,
    reason: str = "",
    tier: str = "",
) -> dict:
    """Record one board/query's discovery coverage for this run.

    Call once per board or query you searched, so a board you never reached
    stays absent from the record rather than getting silently reported as
    "empty" — the operator reads a missing entry as "not reached". ``channel``
    must be one of feed, direct or dork; ``status`` must be one of searched,
    empty, login_walled, blocked, extraction_failed or skipped. ``empty``
    means the search ran and genuinely matched nothing; ``blocked`` means
    the board or query was reachable but the results could not be read — a
    CAPTCHA, a consent interstitial, a bot wall — and must never be reported
    as ``empty``. ``extraction_failed`` means the board was reachable and
    not walled, but harvest could not extract or read its results — never
    reported as ``empty`` or ``blocked``.
    ``deferred`` means not searched this run because of a deliberate pause
    (e.g. Google cooldown/rate-limit), queued for the next run.
    ``tier`` is optional and records which extraction tier produced the
    postings: one of api, harvest or llm, or "" when not applicable.
    """
    if not run_id:
        return {"recorded": False}
    try:
        record = _runs_service.record_coverage(
            run_id, channel, board, status, postings_found, reason, tier
        )
    except Exception:
        return {"recorded": False}
    if record is None:
        return {"recorded": False}
    return {"recorded": True, **record.to_dict()}


def bump_run_counters(run_id: str = "", **counters: int) -> dict:
    """Internal entry point for other tool modules to add to a run's coverage
    counters. Not registered as an agent-facing MCP tool — callers are other
    tool functions, not the model.

    Only ``over_cap_writes`` (a lease violation, with no derivable source) and
    ``postings_seen`` (via ``record_postings_seen``) still have callers. The
    rest — screenings_recorded, blocked_count, queued_for_approval,
    applications_submitted — are derived on read by ``runs/derive.py`` from
    the records the run actually produced, and are not incremented here.
    """
    if not run_id or not counters:
        return {"recorded": False}
    try:
        record = _runs_service.bump_counters(run_id, **counters)
    except Exception:
        return {"recorded": False}
    if record is None:
        return {"recorded": False}
    return {"recorded": True, **record.to_dict()}
