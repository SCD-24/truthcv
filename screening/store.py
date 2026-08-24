"""Persistence for job screening records against the ./data volume.

Mirrors applications/store.py and truth/store.py: one JSON file on the shared
data volume, written atomically (.tmp then replace) so a crash mid-write can
never corrupt the list.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agentconfig.store import load as _agent_config_load
from truth.store import data_dir

from .model import APPROVAL_VALUES, Screening, new_id


def screenings_path() -> Path:
    return data_dir() / "screenings.json"


def _now() -> str:
    """UTC ISO-8601 timestamp; single source so created/updated stay consistent."""
    return datetime.now(timezone.utc).isoformat()


def load_all() -> list[Screening]:
    """Every screening record; empty list if the file is missing or invalid.

    Fails safe on a malformed file (returns []) so a hand-edited or partially
    written JSON never crashes the app on startup.
    """
    p = screenings_path()
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    return [Screening.from_dict(item) for item in raw if isinstance(item, dict)]


def _write_all(screenings: list[Screening]) -> None:
    """Atomically persist the full list to screenings.json."""
    p = screenings_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps([s.to_dict() for s in screenings], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(p)


def get(screening_id: str) -> Screening | None:
    """The screening with this id, or None."""
    return next((s for s in load_all() if s.id == screening_id), None)


def create(fields: dict) -> Screening:
    """Create a new screening record from client-supplied editable fields."""
    now = _now()
    screening = Screening(id=new_id(), created_at=now, updated_at=now)
    _apply_editable(screening, fields)
    # A deferred screening is an unresolved decision, so it enters the operator's
    # approval queue. In semi-auto a *passing* one does too: the operator, not
    # the agent, decides whether to apply. Set here rather than accepted from
    # `fields`: the agent's record_screening reaches this function directly, and
    # approval is not its to grant.
    if screening.verdict == "deferred":
        screening.approval = "pending"
    elif screening.verdict == "passed" and _agent_config_load().mode == "semi":
        screening.approval = "pending"
    screenings = load_all()
    screenings.append(screening)
    _write_all(screenings)
    return screening


def update(screening_id: str, patch: dict) -> Screening | None:
    """Patch a screening's editable fields; returns the updated record."""
    screenings = load_all()
    screening = next((s for s in screenings if s.id == screening_id), None)
    if screening is None:
        return None
    _apply_editable(screening, patch)
    screening.updated_at = _now()
    _write_all(screenings)
    return screening


def delete(screening_id: str) -> bool:
    """Remove a screening record and its orphaned cover-letter draft.

    Returns:
        True if the screening existed and was removed.
    """
    from coverletter import store as _coverletter_store

    screenings = load_all()
    screening = next((s for s in screenings if s.id == screening_id), None)
    if screening is None:
        return False
    _write_all([s for s in screenings if s.id != screening_id])
    _coverletter_store.delete(screening_id)
    return True


def delete_many(ids: list[str]) -> list[tuple[str, bool]]:
    """Remove several screening records (and their draft letters) in one write.

    Loads the list once, writes the survivors once, and removes each deleted
    id's cover-letter draft. Unknown ids are reported False rather than
    raising, so a partially-stale selection from the client is not fatal.

    Args:
        ids: Screening ids to remove, in the order to report results.

    Returns:
        One (id, ok) pair per input id, in input order.
    """
    from coverletter import store as _coverletter_store

    screenings = load_all()
    existing_ids = {s.id for s in screenings}
    to_delete = {i for i in ids if i in existing_ids}
    if to_delete:
        _write_all([s for s in screenings if s.id not in to_delete])
        for deleted_id in to_delete:
            _coverletter_store.delete(deleted_id)
    return [(i, i in to_delete) for i in ids]


def set_approval(screening_id: str, approval: str) -> Screening | None:
    """Set a screening's approval state — the operator's decision, never the agent's.

    Raises ValueError on an unknown state rather than writing it.
    """
    if approval not in APPROVAL_VALUES:
        raise ValueError(f"Unknown approval state '{approval}'.")
    return _mutate(screening_id, lambda s: setattr(s, "approval", approval))


def record_apply_failure(screening_id: str, error: str) -> Screening | None:
    """Count one failed application attempt and keep its error for the operator.

    Leaves `approval` untouched: a failure is not a decision, and the item stays
    queued for the next run.
    """

    def _bump(s: Screening) -> None:
        s.apply_attempts += 1
        s.apply_error = error

    return _mutate(screening_id, _bump)


def mark_applied(screening_id: str) -> Screening | None:
    """Retire an approved item once its application is confirmed."""
    return _mutate(screening_id, lambda s: setattr(s, "approval", "applied"))


def _mutate(screening_id: str, apply) -> Screening | None:
    """Load, mutate one record outside EDITABLE, stamp, and write back."""
    screenings = load_all()
    screening = next((s for s in screenings if s.id == screening_id), None)
    if screening is None:
        return None
    apply(screening)
    screening.updated_at = _now()
    _write_all(screenings)
    return screening


def _apply_editable(screening: Screening, fields: dict) -> None:
    """Copy only whitelisted fields."""
    for key in Screening.EDITABLE:
        if key in fields and fields[key] is not None:
            setattr(screening, key, fields[key])
