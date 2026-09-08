"""JSON-backed persistence for operator-editable prompt fragments and presets.

Seeded fragments and presets (from ``prompts.fragments``) always exist and can
never be edited or deleted; operator-authored ("user") fragments and presets
are layered on top, stored as flat JSON lists in ``data_dir()``. A user record
sharing an id with a seeded one overrides it in the merged view.

Nothing here validates a fragment selection: slots group fragments for
display only, and a preset may combine any number of fragments from any slot.
The default-preset marker lives on its own in ``prompt_default.json`` so that
marking a seeded preset as the default never persists a copy of it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .conventions import CvConventions, DEFAULT_CONVENTIONS
from .fragments import SEEDED_FRAGMENTS, SEEDED_PRESETS, Fragment, Preset, seeded_fragments
from storage.atomic import atomic_write_text, locked
from storage.paths import data_dir

logger = logging.getLogger(__name__)

FRAGMENTS_FILE = "prompt_fragments.json"
PRESETS_FILE = "prompt_presets.json"
DEFAULT_FILE = "prompt_default.json"


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


def list_fragments(conventions: CvConventions = DEFAULT_CONVENTIONS) -> list[Fragment]:
    """Seeded fragments (rendered for ``conventions``) overridden by user ones."""
    merged: dict[str, Fragment] = {f.id: f for f in seeded_fragments(conventions)}
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


def _load_default_marker() -> str | None:
    """Read the default-preset id from ``prompt_default.json``, or ``None``."""
    path = _records_path(DEFAULT_FILE)
    if not path.exists():
        return None
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
        preset_id = marker["presetId"]
        if not isinstance(preset_id, str) or not preset_id:
            raise ValueError("presetId must be a non-empty string")
        return preset_id
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("could not load %s, ignoring default marker: %s", path, exc)
        return None


def _load_preset_records() -> tuple[list[dict[str, Any]], str | None]:
    """User preset records with seeded-id records dropped, plus a legacy default.

    Older versions persisted every merged preset — seeded ones included — into
    ``prompt_presets.json``, which then permanently shadowed the code
    definitions. Those records are dropped on read.

    The second element is the legacy default: the id of whichever persisted
    record carried ``is_default`` before the marker file existed — a user
    preset just as much as a dropped seeded one. Without it, an operator whose
    default was a user preset would silently revert to the seeded default,
    because the seeded "professional" record ships with ``is_default`` true.
    """
    seeded_ids = _seeded_preset_ids()
    kept: list[dict[str, Any]] = []
    legacy_default: str | None = None
    for record in _load_records(PRESETS_FILE):
        if record.get("is_default") and record.get("id"):
            legacy_default = record["id"]
        if record.get("id") in seeded_ids:
            continue
        kept.append(record)
    return kept, legacy_default


def list_presets() -> list[Preset]:
    """Seeded presets overridden/extended by user presets from disk."""
    merged: dict[str, Preset] = {p.id: Preset.from_dict(p.to_dict()) for p in SEEDED_PRESETS}
    records, legacy_default = _load_preset_records()
    for record in records:
        try:
            preset = Preset.from_dict(record)
        except (KeyError, ValueError) as exc:
            logger.warning("skipping corrupt preset record %r: %s", record, exc)
            continue
        merged[preset.id] = preset
    presets = list(merged.values())
    # A marker naming a preset that no longer exists must not mask the legacy
    # flag: fall through to the next candidate rather than silently reverting.
    for candidate in (_load_default_marker(), legacy_default):
        if candidate is not None and any(p.id == candidate for p in presets):
            for preset in presets:
                preset.is_default = preset.id == candidate
            break
    return presets


def get_preset(id: str) -> Preset:
    for preset in list_presets():
        if preset.id == id:
            return preset
    raise KeyError(id)


def default_preset() -> Preset:
    """The preset applied when a caller names none: the marked one, else seeded."""
    defaults = [p for p in list_presets() if p.is_default]
    if defaults:
        return defaults[0]
    # A copy, never the shared module-level object, so no caller can mutate the
    # shipped definition process-wide.
    seeded = next(p for p in SEEDED_PRESETS if p.id == "professional")
    return Preset.from_dict(seeded.to_dict())


def _seeded_preset_ids() -> set[str]:
    return {p.id for p in SEEDED_PRESETS}


def set_default_preset(id: str) -> None:
    """Mark ``id`` as the default preset by writing the standalone marker file.

    Only ``prompt_default.json`` is written: seeded presets are never copied
    into ``prompt_presets.json``, so the shipped definitions keep winning.
    """
    if not any(p.id == id for p in list_presets()):
        raise KeyError(id)
    path = _records_path(DEFAULT_FILE)
    with locked(path):
        atomic_write_text(path, json.dumps({"presetId": id}, indent=2))


def upsert_preset(preset: Preset) -> None:
    if preset.id in _seeded_preset_ids():
        raise ValueError(f"cannot edit seeded preset {preset.id}")
    path = _records_path(PRESETS_FILE)
    with locked(path):
        records, _ = _load_preset_records()
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
        records, _ = _load_preset_records()
        records = [r for r in records if r.get("id") != id]
        atomic_write_text(path, json.dumps(records, indent=2))
