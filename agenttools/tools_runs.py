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
silently ending a partial run. See ``_coverage_shortfall``. When the caller
does not pass ``turns_remaining`` this is the legacy one-shot guard: the
FIRST such call raises and a second always closes the run. When the harness
does pass ``turns_remaining`` the guard is harness-aware instead: it keeps
refusing (up to ``_MAX_FINISH_REFUSALS`` times) as long as there is enough
run left to act on the refusal, and lets the call through once turns are
nearly exhausted or the refusal cap is reached. ``finish_phase`` offers a
non-terminal way to report the same shortfall mid-run, per channel, without
ever touching run status.
"""

from __future__ import annotations

import runs.store as _runs_store
from runs.model import validate_status as _validate_status

# How many turns must remain for the finish guard to still be allowed to
# refuse — below this, refusing would strand the model with no turns left to
# act on the refusal, so the call is let through instead.
_FINISH_GUARD_RESERVE_TURNS = 2
# How many times the guard will refuse a single run (or, for finish_phase, a
# single channel) before giving up and letting the call through regardless.
_MAX_FINISH_REFUSALS = 3


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

_FINISH_REFUSAL_INSTRUCTIONS_HARNESS_AWARE = (
    "Discovery is not finished — go back and work these boards/queries and "
    "record_discovery_coverage for each. created:false feed results are not "
    "a reason to stop. Calling finish_run again while coverage is short and "
    "turns remain will keep being refused, up to a small cap, not recorded."
)


def _channel_coverage(record, channel: str) -> tuple[int, list[str]]:
    """(worked count, skipped board/query names) for one discovery channel,
    read straight from ``record.discovery_coverage`` — no config involved, so
    this can never fail on a config error."""
    entries = [e for e in record.discovery_coverage if e.get("channel") == channel]
    worked = sum(1 for e in entries if e.get("status") != "skipped")
    skipped = [e.get("board", "") for e in entries if e.get("status") == "skipped"]
    return worked, skipped


def _expected_counts() -> dict[str, int]:
    """{'direct': N, 'dork': N} expected counts from the current agent
    config, or {} on any error (config load/compose failure). Isolated from
    ``_channel_coverage`` so a broken config only drops the count comparison,
    never the skipped-entry check, which needs no config at all.
    """
    try:
        from agentconfig import store as _agentconfig_store
        from agentconfig.dorks import compose_direct_boards, compose_queries

        cfg = _agentconfig_store.load()
        resolved = cfg.resolved_boards()
        return {
            "direct": len(compose_direct_boards(cfg.profiles, resolved)),
            "dork": len(compose_queries(cfg.profiles, cfg.max_posting_age_days, resolved)),
        }
    except Exception:
        return {}


def _coverage_shortfall(record, channels: tuple[str, ...] = ("direct", "dork")) -> list[str]:
    """Shortfall messages for the given discovery channels, or [] when they
    look complete.

    A channel with any 'skipped' entry is ALWAYS flagged, by name, straight
    from the record — that check needs no config and so cannot be defeated by
    a config-load error. Separately, when the current config's expected count
    for a channel is available, a worked count below it is also flagged; a
    config error drops only this half of the check, never the skipped-entry
    half.
    """
    expected = _expected_counts()
    messages = []
    for channel in channels:
        worked, skipped = _channel_coverage(record, channel)
        want = expected.get(channel)
        short = skipped or (want is not None and worked < want)
        if not short:
            continue
        if want is not None:
            detail = f", skipped: {', '.join(skipped)}" if skipped else ""
            messages.append(f"{channel}: worked {worked}/{want}{detail}")
        else:
            messages.append(f"{channel}: skipped: {', '.join(skipped)}")
    return messages


def _normalized_status(status: str) -> str:
    """``status`` as the store would see it (``runs.model.validate_status``:
    stripped and casefolded), or the same fallback normalization if that
    raises — a raw ``!= "completed"`` comparison let a trailing space or
    different case (e.g. "Completed ") slip past the guard entirely even
    though the store itself would treat it as completed.
    """
    try:
        return _validate_status(status)
    except Exception:
        return status.strip().casefold() if isinstance(status, str) else ""


def _guard_incomplete_discovery(run_id: str, status: str, turns_remaining: int) -> None:
    """Raise ValueError, and record the refusal, when a finish_run call for a
    run whose discovery coverage looks short should still be refused.

    Two modes, selected by whether the caller passed ``turns_remaining``:

    - Legacy one-shot (``turns_remaining < 0``): refuses only the FIRST call
      for this run (``record.finish_refused`` not yet set); a second call
      always goes through.
    - Harness-aware (``turns_remaining >= 0``): keeps refusing, up to
      ``_MAX_FINISH_REFUSALS`` times, as long as more than
      ``_FINISH_GUARD_RESERVE_TURNS`` turns remain — refusing with no turns
      left to act on it would just strand the run.
    """
    if _normalized_status(status) != "completed":
        return
    record = _runs_store.get(run_id)
    if record is None:
        return
    shortfall = _coverage_shortfall(record, channels=("feed", "direct", "dork"))
    if not shortfall:
        return
    if turns_remaining < 0:
        should_refuse = not record.finish_refused
    else:
        should_refuse = (
            turns_remaining > _FINISH_GUARD_RESERVE_TURNS
            and record.finish_refusals < _MAX_FINISH_REFUSALS
        )
    if not should_refuse:
        return
    _runs_store.mark_finish_refused(run_id)
    if turns_remaining >= 0:
        message = (
            "; ".join(shortfall)
            + ". "
            + _FINISH_REFUSAL_INSTRUCTIONS_HARNESS_AWARE
            + f" turns_remaining={turns_remaining}. The turn limit is NOT a "
            "valid stopped_reason while turns remain — use them to finish "
            "discovery instead."
        )
    else:
        message = "; ".join(shortfall) + ". " + _FINISH_REFUSAL_INSTRUCTIONS
    raise ValueError(message)


def finish_run(
    run_id: str = "",
    status: str = "completed",
    stopped_reason: str = "",
    note: str = "",
    turns_remaining: int = -1,
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
    """
    if not run_id:
        return {"recorded": False}
    _guard_incomplete_discovery(run_id, status, turns_remaining)
    try:
        record = _runs_store.finish(
            run_id, status=status, stopped_reason=stopped_reason, note=note
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
    if channel not in ("feed", "direct", "dork"):
        return {"recorded": False, "error": "channel must be one of feed, direct, dork"}
    if not run_id:
        return {"recorded": False, "error": "run_id required"}
    record = _runs_store.get(run_id)
    if record is None:
        return {"recorded": False, "error": "unknown run_id"}

    shortfall = _coverage_shortfall(record, channels=(channel,))
    if (
        shortfall
        and turns_remaining > _FINISH_GUARD_RESERVE_TURNS
        and record.phase_refusals.get(channel, 0) < _MAX_FINISH_REFUSALS
    ):
        _runs_store.record_phase_refusal(run_id, channel)
        message = (
            f"[{channel}] "
            + "; ".join(shortfall)
            + ". "
            + _FINISH_REFUSAL_INSTRUCTIONS_HARNESS_AWARE
        )
        message += (
            f" turns_remaining={turns_remaining}. The turn limit is NOT a "
            "valid stopped_reason while turns remain — use them to finish "
            "discovery instead."
        )
        raise ValueError(message)

    if note:
        tagged = f"[{channel}] {note}"
        _runs_store.append_note(run_id, tagged)
    return {"recorded": True, "channel": channel, "shortfall": shortfall}


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
