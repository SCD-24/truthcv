"""Persistence for job screening records against the ./data volume.

Mirrors applications/store.py and truth/store.py: one JSON file on the shared
data volume, written atomically (.tmp then replace) so a crash mid-write can
never corrupt the list.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from truth.store import data_dir

from .model import Screening, new_id


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
    """Remove a screening record. True if it existed."""
    screenings = load_all()
    screening = next((s for s in screenings if s.id == screening_id), None)
    if screening is None:
        return False
    _write_all([s for s in screenings if s.id != screening_id])
    return True


def _apply_editable(screening: Screening, fields: dict) -> None:
    """Copy only whitelisted fields."""
    for key in Screening.EDITABLE:
        if key in fields and fields[key] is not None:
            setattr(screening, key, fields[key])
