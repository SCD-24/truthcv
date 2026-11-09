"""Run lifecycle logic shared by the agent tool surface.

The discovery-coverage guard, the per-channel ``finish_phase`` check and the
coverage allow-lists live here so the tool adapters in
``agenttools/tools_runs.py`` only parse input and translate results.
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
