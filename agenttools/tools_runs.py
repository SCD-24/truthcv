"""Run lifecycle tools for the agent tool surface.

Every function here is best-effort accountability, never a thing that can
fail a run: a run record exists so a partial or crashed run leaves behind an
honest coverage summary, not so a forgetful tool call can abort the agent
mid-application. Every parameter has a default (agenttools/mcp_app.py derives
the JSON schema from ``inspect.signature`` and marks a defaultless parameter
required, which would turn a forgetful model call into a mid-run TypeError),
and every function no-ops on an empty ``run_id`` rather than raising.

One deliberate exception: ``finish_run`` raises ``ValueError`` the FIRST time
it is called on a run whose direct-board or dork-query discovery coverage
looks incomplete, so the model is sent back to finish discovery instead of
silently ending a partial run. See ``_coverage_shortfall``. A second call
always closes the run.
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


_FINISH_REFUSAL_INSTRUCTIONS = (
    "Discovery is not finished — go back and work these boards/queries and "
    "record_discovery_coverage for each. created:false feed results are not "
    "a reason to stop. If you genuinely cannot continue (turn limit, "
    "browser down), call finish_run again with an honest stopped_reason and "
    "it will be recorded."
)


def _coverage_shortfall(record) -> list[str]:
    """Per-channel shortfall messages for the run's direct/dork discovery
    coverage against what the current config expects, or [] when it looks
    complete. Counts are compared, never status labels (free text), and a
    channel with any 'skipped' entry is always flagged even if its count is
    otherwise met. Any error here (e.g. config load failure) must not block
    finish_run, so it fails safe to [].
    """
    try:
        from agentconfig import store as _agentconfig_store
        from agentconfig.dorks import compose_direct_boards, compose_queries

        cfg = _agentconfig_store.load()
        resolved = cfg.resolved_boards()
        expected = {
            "direct": len(compose_direct_boards(cfg.profiles, resolved)),
            "dork": len(compose_queries(cfg.profiles, cfg.max_posting_age_days, resolved)),
        }
        messages = []
        for channel, want in expected.items():
            entries = [e for e in record.discovery_coverage if e.get("channel") == channel]
            worked = sum(1 for e in entries if e.get("status") != "skipped")
            skipped = [e.get("board", "") for e in entries if e.get("status") == "skipped"]
            if worked < want or skipped:
                detail = f", skipped: {', '.join(skipped)}" if skipped else ""
                messages.append(f"{channel}: worked {worked}/{want}{detail}")
        return messages
    except Exception:
        return []


def _guard_incomplete_discovery(run_id: str, status: str) -> None:
    """Raise ValueError, and mark the record refused, on the first
    finish_run call for a run whose discovery coverage looks short. A
    second call sees ``finish_refused`` already set and lets it through.
    """
    if status != "completed":
        return
    record = _runs_store.get(run_id)
    if record is None or record.finish_refused:
        return
    shortfall = _coverage_shortfall(record)
    if not shortfall:
        return
    _runs_store.mark_finish_refused(run_id)
    raise ValueError("; ".join(shortfall) + ". " + _FINISH_REFUSAL_INSTRUCTIONS)


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

    Raises ValueError, and refuses to close the run, on the FIRST call for a
    'completed' run whose direct-board or dork-query discovery coverage
    looks incomplete — deliberately, to send the model back to finish
    discovery rather than let it stop early unnoticed. A second finish_run
    call for the same run always succeeds.
    """
    if not run_id:
        return {"recorded": False}
    _guard_incomplete_discovery(run_id, status)
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
        record = _runs_store.bump(run_id, postings_seen=count)
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
    empty, login_walled, blocked or skipped. ``empty`` means the search ran
    and genuinely matched nothing; ``blocked`` means the board or query was
    reachable but the results could not be read — a CAPTCHA, a consent
    interstitial, a bot wall — and must never be reported as ``empty``.
    ``tier`` is optional and records which extraction tier produced the
    postings: one of api, harvest or llm, or "" when not applicable.
    """
    if not run_id:
        return {"recorded": False}
    if channel not in ("feed", "direct", "dork"):
        return {"recorded": False}
    if status not in ("searched", "empty", "login_walled", "blocked", "skipped"):
        return {"recorded": False}
    if tier not in ("api", "harvest", "llm", ""):
        return {"recorded": False}
    entry = {
        "channel": channel,
        "board": board,
        "status": status,
        "postings_found": postings_found,
        "reason": reason,
        "tier": tier,
    }
    try:
        record = _runs_store.add_discovery_coverage(run_id, entry)
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
        record = _runs_store.bump(run_id, **counters)
    except Exception:
        return {"recorded": False}
    if record is None:
        return {"recorded": False}
    return {"recorded": True, **record.to_dict()}
