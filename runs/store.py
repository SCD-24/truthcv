"""Persistence for agent run records against the ./data volume.

Mirrors screening/store.py: one JSON file on the shared data volume. Every
mutator runs its whole load-modify-write inside ``datafile.locked`` for the
same reason screenings do — the API and the agent's MCP tools can both touch
this file, and an unguarded load-modify-write silently drops one writer's
change.

Deliberately NOT modelled on agentconfig/store.py, which hand-rolls its own
write and takes no lock: a run record is written far more often (every tool
call bumps a counter) and losing one silently is exactly the failure mode
this store exists to avoid.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from storage import atomic_write_text, locked
from storage import data_dir

from .model import RunRecord, new_id, validate_status

# Keep only the most recent N run records; older ones are dropped on write so
# runs.json cannot grow without bound over the life of the deployment.
_MAX_RECORDS = 200


def runs_path() -> Path:
    return data_dir() / "runs.json"


def _now() -> str:
    """UTC ISO-8601 timestamp; single source so started/finished stay consistent."""
    return datetime.now(timezone.utc).isoformat()


def load_all() -> list[RunRecord]:
    """Every run record; empty list if the file is missing or invalid.

    Fails safe on a malformed file (returns []) so a hand-edited or partially
    written JSON never crashes the app on startup.
    """
    p = runs_path()
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    return [RunRecord.from_dict(item) for item in raw if isinstance(item, dict)]


def _write_all(runs: list[RunRecord]) -> None:
    """Persist the full list to runs.json.

    Callers must already hold ``locked(runs_path())`` — this writes the list
    it is given and does no reconciliation, so an unguarded caller overwrites
    whatever another writer stored since it loaded. Retention (most recent
    ``_MAX_RECORDS``) is enforced here so every write path gets it for free.
    """
    trimmed = sorted(runs, key=lambda r: r.started_at)[-_MAX_RECORDS:]
    atomic_write_text(
        runs_path(),
        json.dumps([r.to_dict() for r in trimmed], indent=2, ensure_ascii=False),
    )


def get(run_id: str) -> RunRecord | None:
    """The run record with this id, or None."""
    return next((r for r in load_all() if r.id == run_id), None)


def list_recent(limit: int = 50, offset: int = 0) -> list[RunRecord]:
    """One page of the most recently started runs, newest first.

    ``offset`` skips that many of the newest runs before the page starts, so
    the caller can page backwards through history. It is applied BEFORE the
    limit, and an offset past the end yields an empty list rather than an
    error — a page that no longer exists (runs were pruned, or the caller held
    a stale page number) is an empty page, not a failure.

    ``limit`` of 0 or less still means "no limit", which is what the callers
    that want the whole history rely on.
    """
    runs = sorted(load_all(), key=lambda r: r.started_at, reverse=True)
    if offset > 0:
        runs = runs[offset:]
    if limit and limit > 0:
        return runs[:limit]
    return runs


def count() -> int:
    """How many runs are currently retained.

    Not "how many have ever run": `_write_all` keeps only the newest
    `_MAX_RECORDS`, so this counts what is on the volume now.

    Separate from list_recent because a paginated caller needs the total to
    know how many pages there are, and deriving it from a page is impossible
    once the page is capped. A caller that needs the page and the total to
    describe the same file should use `list_page`, which reads once.
    """
    return len(load_all())


def list_page(limit: int = 50, offset: int = 0) -> tuple[list[RunRecord], int]:
    """One page of runs and the total they were drawn from, from ONE read.

    `list_recent` followed by `count` reads runs.json twice, and a run can be
    recorded between the two: the response then pairs a page with a total that
    describes a different file, and reports an older run as newly hidden. One
    read cannot disagree with itself.
    """
    runs = sorted(load_all(), key=lambda r: r.started_at, reverse=True)
    total = len(runs)
    if offset > 0:
        runs = runs[offset:]
    if limit and limit > 0:
        runs = runs[:limit]
    return runs, total


def start(run_id: str, trigger: str = "", apply_cap: int = 0) -> RunRecord:
    """Begin a run record. Idempotent: starting an id that already exists
    returns the existing record unchanged rather than resetting it — a
    forgetful agent calling start_run twice must not lose the first call's
    coverage counters.
    """
    with locked(runs_path()):
        runs = load_all()
        existing = next((r for r in runs if r.id == run_id), None)
        if existing is not None:
            return existing
        record = RunRecord(
            id=run_id or new_id(),
            started_at=_now(),
            status="running",
            trigger=trigger,
            apply_cap=apply_cap,
        )
        runs.append(record)
        _write_all(runs)
        return record


def bump(run_id: str, **counters: int) -> RunRecord | None:
    """Add each keyword's value to the same-named counter field on the run.

    Unknown counter names are ignored rather than raising: this is called
    from best-effort tool code, and a typo here must not be able to fail a
    run.
    """
    with locked(runs_path()):
        runs = load_all()
        record = next((r for r in runs if r.id == run_id), None)
        if record is None:
            return None
        for key, delta in counters.items():
            if hasattr(record, key) and isinstance(getattr(record, key), int):
                setattr(record, key, getattr(record, key) + int(delta))
        _write_all(runs)
        return record


def set_note(run_id: str, note: str) -> RunRecord | None:
    """Set (overwrite) the run's free-text note."""
    with locked(runs_path()):
        runs = load_all()
        record = next((r for r in runs if r.id == run_id), None)
        if record is None:
            return None
        record.note = note
        _write_all(runs)
        return record


def add_discovery_coverage(run_id: str, entry: dict) -> RunRecord | None:
    """Append one discovery-coverage entry to the run's record."""
    with locked(runs_path()):
        runs = load_all()
        record = next((r for r in runs if r.id == run_id), None)
        if record is None:
            return None
        record.discovery_coverage.append(entry)
        _write_all(runs)
        return record


def finish_if_running(
    run_id: str,
    status: str = "failed",
    stopped_reason: str = "",
) -> RunRecord | None:
    """Close out a run record only while it is still ``running``.

    The host side (agent/supervisor.js) closes every run out when the child
    exits, so a run that died before the model could call ``finish_run`` still
    ends with an honest status instead of sitting at "running" forever. But the
    model's own ``finish_run`` is the better account when it happened — it names
    where the run actually stopped — so this must never overwrite a record that
    already reached a terminal status. Returns None when there is no such record
    or it is already finished; both are no-ops, not errors.
    """
    with locked(runs_path()):
        runs = load_all()
        record = next((r for r in runs if r.id == run_id), None)
        if record is None or record.status != "running":
            return None
        record.status = validate_status(status)
        record.finished_at = _now()
        record.stopped_reason = stopped_reason
        _write_all(runs)
        return record


def finish(
    run_id: str,
    status: str = "completed",
    stopped_reason: str = "",
    note: str = "",
) -> RunRecord | None:
    """Close out a run record with its terminal status and coverage answer."""
    with locked(runs_path()):
        runs = load_all()
        record = next((r for r in runs if r.id == run_id), None)
        if record is None:
            return None
        record.status = validate_status(status)
        record.finished_at = _now()
        record.stopped_reason = stopped_reason
        if note:
            record.note = note
        _write_all(runs)
        return record
