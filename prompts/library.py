"""JSON-backed persistence for operator-editable prompt fragments and presets.

Seeded fragments and presets (from ``prompts.fragments``) always exist and can
never be edited or deleted; operator-authored ("user") fragments and presets
are layered on top, stored as flat JSON lists in ``data_dir()``. A user record
sharing an id with a seeded one overrides it in the merged view.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .conventions import DEFAULT_CONVENTIONS
from .fragments import EXCLUSIVE_SLOTS, SEEDED_FRAGMENTS, SEEDED_PRESETS, Fragment, Preset
from storage.atomic import atomic_write_text, locked
from storage.paths import data_dir

logger = logging.getLogger(__name__)

FRAGMENTS_FILE = "prompt_fragments.json"
PRESETS_FILE = "prompt_presets.json"


@dataclass
class Conflict:
    """One reason a preset's fragment selection is invalid."""

    kind: str
    fragment_ids: list[str]
    slot: str | None
    message: str


class PresetConflictError(Exception):
    """Raised by ``upsert_preset`` when the fragment selection has conflicts."""

    def __init__(self, conflicts: list[Conflict]) -> None:
        self.conflicts = conflicts
        super().__init__("; ".join(c.message for c in conflicts))


def _records_path(filename: str) -> Path:
    return data_dir() / filename


def _load_records(filename: str) -> list[dict[str, Any]]:
    """Load a JSON list of dicts from ``filename``, or ``[]`` on absence/corruption."""
    path = _records_path(filename)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
        records = json.loads(text)
        if not isinstance(records, list):
            raise ValueError("expected a JSON list")
        return records
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("could not load %s, falling back to seeded only: %s", path, exc)
        return []


def list_fragments(conventions=DEFAULT_CONVENTIONS) -> list[Fragment]:
    """Seeded fragments overridden/extended by user fragments from disk."""
    merged: dict[str, Fragment] = {f.id: f for f in SEEDED_FRAGMENTS}
    for record in _load_records(FRAGMENTS_FILE):
        try:
            fragment = Fragment.from_dict(record)
        except (KeyError, ValueError) as exc:
            logger.warning("skipping corrupt fragment record %r: %s", record, exc)
            continue
        merged[fragment.id] = fragment
    return list(merged.values())


def get_fragment(id: str) -> Fragment:
    for fragment in list_fragments():
        if fragment.id == id:
            return fragment
    raise KeyError(id)


def _seeded_fragment_ids() -> set[str]:
    return {f.id for f in SEEDED_FRAGMENTS}


def upsert_fragment(fragment: Fragment) -> None:
    if fragment.id in _seeded_fragment_ids():
        raise ValueError(f"cannot edit seeded fragment {fragment.id}")
    path = _records_path(FRAGMENTS_FILE)
    with locked(path):
        records = _load_records(FRAGMENTS_FILE)
        records = [r for r in records if r.get("id") != fragment.id]
        records.append(fragment.to_dict())
        atomic_write_text(path, json.dumps(records, indent=2))


def delete_fragment(id: str) -> None:
    if id in _seeded_fragment_ids():
        raise ValueError(f"cannot delete seeded fragment {id}")
    for preset in list_presets():
        if id in preset.fragment_ids:
            raise ValueError(f"fragment {id} is referenced by preset {preset.id}")
    path = _records_path(FRAGMENTS_FILE)
    with locked(path):
        records = _load_records(FRAGMENTS_FILE)
        records = [r for r in records if r.get("id") != id]
        atomic_write_text(path, json.dumps(records, indent=2))


def list_presets() -> list[Preset]:
    """Seeded presets overridden/extended by user presets from disk."""
    merged: dict[str, Preset] = {p.id: p for p in SEEDED_PRESETS}
    for record in _load_records(PRESETS_FILE):
        try:
            preset = Preset.from_dict(record)
        except (KeyError, ValueError) as exc:
            logger.warning("skipping corrupt preset record %r: %s", record, exc)
            continue
        merged[preset.id] = preset
    return list(merged.values())


def get_preset(id: str) -> Preset:
    for preset in list_presets():
        if preset.id == id:
            return preset
    raise KeyError(id)


def default_preset() -> Preset:
    defaults = [p for p in list_presets() if p.is_default]
    if defaults:
        return defaults[0]
    return next(p for p in SEEDED_PRESETS if p.id == "professional")


def _seeded_preset_ids() -> set[str]:
    return {p.id for p in SEEDED_PRESETS}


def set_default_preset(id: str) -> None:
    presets = list_presets()
    if not any(p.id == id for p in presets):
        raise KeyError(id)
    path = _records_path(PRESETS_FILE)
    with locked(path):
        records = []
        for preset in presets:
            preset.is_default = preset.id == id
            records.append(preset.to_dict())
        atomic_write_text(path, json.dumps(records, indent=2))


def upsert_preset(preset: Preset) -> None:
    if preset.id in _seeded_preset_ids():
        raise ValueError(f"cannot edit seeded preset {preset.id}")
    conflicts = validate_preset(preset.fragment_ids)
    if conflicts:
        raise PresetConflictError(conflicts)
    path = _records_path(PRESETS_FILE)
    with locked(path):
        records = _load_records(PRESETS_FILE)
        records = [r for r in records if r.get("id") != preset.id]
        records.append(preset.to_dict())
        atomic_write_text(path, json.dumps(records, indent=2))


def delete_preset(id: str) -> None:
    if id in _seeded_preset_ids():
        raise ValueError(f"cannot delete seeded preset {id}")
    if default_preset().id == id:
        raise ValueError("cannot delete default preset")
    path = _records_path(PRESETS_FILE)
    with locked(path):
        records = _load_records(PRESETS_FILE)
        records = [r for r in records if r.get("id") != id]
        atomic_write_text(path, json.dumps(records, indent=2))


def _exclusive_slot_conflicts(fragment_ids: list[str], fragments_by_id: dict[str, Fragment]) -> list[Conflict]:
    conflicts: list[Conflict] = []
    seen_by_slot: dict[str, str] = {}
    for fid in fragment_ids:
        fragment = fragments_by_id.get(fid)
        if fragment is None or fragment.slot not in EXCLUSIVE_SLOTS:
            continue
        prior = seen_by_slot.get(fragment.slot)
        if prior is not None:
            conflicts.append(Conflict(
                kind="exclusive_slot",
                fragment_ids=[prior, fid],
                slot=fragment.slot,
                message=f"Fragments {prior} and {fid} both use slot {fragment.slot}",
            ))
        else:
            seen_by_slot[fragment.slot] = fid
    return conflicts


def _declared_conflicts(fragment_ids: list[str], fragments_by_id: dict[str, Fragment]) -> list[Conflict]:
    conflicts: list[Conflict] = []
    for fid in fragment_ids:
        fragment = fragments_by_id.get(fid)
        if fragment is None:
            continue
        for other_id in fragment_ids:
            other = fragments_by_id.get(other_id)
            if other is None or other.id == fragment.id:
                continue
            if other.id in fragment.conflicts_with:
                conflicts.append(Conflict(
                    kind="declared",
                    fragment_ids=[fragment.id, other.id],
                    slot=None,
                    message=f"Fragment {other.id} declared conflict with {fragment.id}",
                ))
    return conflicts


def validate_preset(fragment_ids: list[str], fragments: list[Fragment] | None = None) -> list[Conflict]:
    if fragments is None:
        fragments = list_fragments()
    fragments_by_id = {f.id: f for f in fragments}
    conflicts: list[Conflict] = []
    conflicts.extend(_exclusive_slot_conflicts(fragment_ids, fragments_by_id))
    conflicts.extend(_declared_conflicts(fragment_ids, fragments_by_id))
    for fid in fragment_ids:
        if fid not in fragments_by_id:
            conflicts.append(Conflict(
                kind="unknown_fragment",
                fragment_ids=[fid],
                slot=None,
                message=f"Unknown fragment {fid}",
            ))
    return conflicts
