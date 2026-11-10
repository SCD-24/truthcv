"""Run lifecycle logic shared by the agent tool surface.

The discovery-coverage guard, the per-channel ``finish_phase`` check and the
coverage allow-lists live here so the tool adapters in
``agenttools/tools_runs.py`` only parse input and translate results.
"""

from __future__ import annotations

import logging

import applications as _app_store
import runs.store as _runs_store
from runs import url_ledger as _url_ledger
from runs.derive import board_breakdown_by_run, counters_by_run
from runs.model import validate_status as _validate_status
from runs.url_ledger import OUTCOMES as _FUNNEL_OUTCOMES
from screening import store as _screening_store
from services import supervisor as _supervisor
from services.errors import BadRequest, Conflict, NotFound, ServiceError

logger = logging.getLogger(__name__)

# How many turns must remain for the finish guard to still be allowed to
# refuse — below this, refusing would strand the model with no turns left to
# act on the refusal, so the call is let through instead.
_FINISH_GUARD_RESERVE_TURNS = 2
# How many times the guard will refuse a single run (or, for finish_phase, a
# single channel) before giving up and letting the call through regardless.
_MAX_FINISH_REFUSALS = 3

CHANNELS = ("feed", "direct", "dork")
COVERAGE_STATUSES = (
    "searched",
    "empty",
    "login_walled",
    "blocked",
    "extraction_failed",
    "skipped",
    "deferred",
)
COVERAGE_TIERS = ("api", "harvest", "llm", "")


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
    # 'deferred' (deliberate pause, queued for next run) counts as worked.
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
        searched = cfg.searched_boards()
        return {
            "direct": len(compose_direct_boards(cfg.profiles, searched)),
            "dork": len(compose_queries(cfg.profiles, cfg.dork_recency, searched)),
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


def guard_finish(run_id: str, status: str, turns_remaining: int) -> None:
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


def finish_phase(run_id: str, channel: str, note: str, turns_remaining: int) -> dict:
    """Per-channel, non-terminal discovery check-in for a run.

    Lives here so the refusal rules (reserve turns, per-channel cap) sit next
    to the finish_run guard they mirror. Returns the wire dict; raises
    ValueError with the harness-aware refusal when the channel is short and
    turns remain.
    """
    if channel not in CHANNELS:
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


def record_coverage(
    run_id: str,
    channel: str,
    board: str,
    status: str,
    postings_found: int,
    reason: str,
    tier: str,
):
    """Validate against the allow-lists and store one discovery-coverage entry.

    Returns the updated record, or None when any value is outside its
    allow-list or the run is unknown, so the adapter can answer with a bare
    ``{"recorded": False}``. Store errors propagate to the caller.
    """
    if channel not in CHANNELS:
        return None
    if status not in COVERAGE_STATUSES:
        return None
    if tier not in COVERAGE_TIERS:
        return None
    entry = {
        "channel": channel,
        "board": board,
        "status": status,
        "postings_found": postings_found,
        "reason": reason,
        "tier": tier,
    }
    return _runs_store.add_discovery_coverage(run_id, entry)


def bump_counters(run_id: str, **counters: int):
    """Add to a run's coverage counters; returns the updated record or None.

    Shared entry point for the postings_seen tool and other tool modules
    (over_cap_writes). Store errors propagate to the caller.
    """
    return _runs_store.bump(run_id, **counters)


# Page size bounds for the run URL ledger.
URL_LEDGER_DEFAULT_LIMIT = 50
URL_LEDGER_MAX_LIMIT = 200


def _run_dicts(records: list) -> list[dict]:
    """Run records as wire-ready dicts, with their coverage counters DERIVED.

    screenings_recorded, blocked_count, queued_for_approval and
    applications_submitted are recomputed from the records each run actually
    produced and OVERRIDE whatever is stored on the run record; postings_seen,
    over_cap_writes, stopped_reason, note, status and the timestamps are read
    from the stored record unchanged. board_breakdown is derived from screenings
    per board. Both run routes go through here so the two surfaces cannot
    disagree — the same reasoning check_cooldown gives for sharing one function.

    Each store is loaded ONCE for the whole list, not once per run. A run still
    "running" derives live counts, which is intended: the numbers describe the
    records that exist right now.

    Derivation is best-effort, in the spirit of the rest of this subsystem: if
    a store cannot be loaded, the stored values are served rather than failing
    the request. Only the load is guarded, not the response build.
    """
    try:
        screenings = _screening_store.load_all()
        applications = _app_store.load_all()
    except Exception:
        return [r.to_dict() for r in records]
    counters = counters_by_run([r.id for r in records], screenings, applications)
    breakdown = board_breakdown_by_run(records, screenings)
    return [
        {
            **r.to_dict(),
            **counters.get(r.id, {}),
            "board_breakdown": breakdown[r.id]["rows"],
            "board_breakdown_total": breakdown[r.id]["total"],
        }
        for r in records
    ]


def list_runs_page(limit: int, offset: int) -> tuple[list[dict], int]:
    """One page of the most recently started runs (newest first) as dicts,
    plus the total.

    Reads the shared data volume in-process via runs.store — this does NOT
    proxy to the supervisor. The caller is expected to have clamped a negative
    offset already; the page and its total come from one read of the store so
    they always describe the same set of runs.
    """
    records, total = _runs_store.list_page(limit=limit, offset=offset)
    return _run_dicts(records), total


def get_run(run_id: str) -> dict:
    """A single run as a wire-ready dict; NotFound if none was recorded."""
    record = _runs_store.get(run_id)
    if record is None:
        raise NotFound("run not found")
    return _run_dicts([record])[0]


def url_ledger_page(
    run_id: str,
    source: str = "",
    outcome: str = "",
    limit: int = URL_LEDGER_DEFAULT_LIMIT,
    offset: int = 0,
    channel: str = "",
) -> tuple[list, int]:
    """One page of the run's URL ledger, optionally filtered by source and
    outcome. NotFound for an unknown run, BadRequest for an unknown outcome or
    channel; limit is clamped to 1..URL_LEDGER_MAX_LIMIT and a negative offset
    to 0."""
    if _runs_store.get(run_id) is None:
        raise NotFound("run not found")
    if outcome and outcome not in _FUNNEL_OUTCOMES:
        raise BadRequest("unknown outcome")
    if channel and channel not in ("feed", "direct", "dork"):
        raise BadRequest("unknown channel")
    limit = min(max(1, limit), URL_LEDGER_MAX_LIMIT)
    return _url_ledger.read(run_id, source, outcome, limit, max(0, offset), channel)


def _supervisor_owns_run(run_id: str) -> bool:
    """Whether the supervisor is the one currently watching this run.

    The supervisor tracks only what it currently owns, in memory: if its
    status does not name this run as the one it is running, nothing will ever
    call finish_run for it — the run is orphaned and we close it ourselves.
    """
    try:
        data = _supervisor.forward_to_supervisor("/status")
    except ServiceError as exc:
        logger.warning("could not reach supervisor to check run ownership: %s", exc)
        return False
    return data.get("running") is True and data.get("currentRunId") == run_id


def stop_run(run_id: str) -> tuple[str, dict]:
    """Stop a run: cancel it through the supervisor if it owns the run, or
    close an orphaned record as failed/orphaned otherwise. Returns
    (outcome, run dict) where outcome is "cancelling" or "closed".
    """
    record = _runs_store.get(run_id)
    if record is None:
        raise NotFound("run not found")
    if record.status != "running":
        raise Conflict("run is not running", payload="run is not running")

    if _supervisor_owns_run(run_id):
        _supervisor.forward_to_supervisor("/cancel", method="POST")
        return "cancelling", _run_dicts([record])[0]

    closed = _runs_store.finish_if_running(run_id, "failed", stopped_reason="orphaned")
    if closed is None:
        closed = _runs_store.get(run_id)
    return "closed", _run_dicts([closed])[0]


def reconcile_orphaned_runs() -> list:
    """Reconcile orphaned runs at API startup.

    Checks which run (if any) the supervisor currently owns, then closes
    every other "running" record as orphaned — those have nothing left that
    could ever close them, since the supervisor keeps run state in memory.
    """
    live_run_id = None
    try:
        data = _supervisor.forward_to_supervisor("/status")
        if data.get("running") is True:
            live_run_id = data.get("currentRunId")
    except ServiceError:
        logger.warning(
            "Supervisor was unreachable during startup reconciliation; "
            "all running records will be treated as orphaned"
        )

    closed = _runs_store.close_orphaned(except_run_id=live_run_id)
    logger.info(
        "reconciled orphaned runs at startup",
        extra={"count": len(closed), "closed_run_ids": [r.id for r in closed]},
    )
    return closed
