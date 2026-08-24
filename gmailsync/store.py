from __future__ import annotations

import json
from pathlib import Path

from truth.store import data_dir

from .model import GmailSuggestion, GmailSyncState


def sync_state_path() -> Path:
    return data_dir() / "gmail_sync.json"


def suggestions_path() -> Path:
    return data_dir() / "gmail_suggestions.json"


def _write_json(path: Path, payload) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_sync_state() -> GmailSyncState:
    path = sync_state_path()
    if not path.exists():
        return GmailSyncState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return GmailSyncState()
    if not isinstance(raw, dict):
        return GmailSyncState()
    return GmailSyncState.from_dict(raw)


def save_sync_state(state: GmailSyncState) -> None:
    _write_json(sync_state_path(), state.to_dict())


def load_suggestions() -> list[GmailSuggestion]:
    path = suggestions_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    return [GmailSuggestion.from_dict(item) for item in raw if isinstance(item, dict)]


def save_suggestions(items: list[GmailSuggestion]) -> None:
    _write_json(suggestions_path(), [item.to_dict() for item in items])


def update_suggestion_state(suggestion_id: str, state: str) -> GmailSuggestion | None:
    suggestions = load_suggestions()
    target = next((item for item in suggestions if item.id == suggestion_id), None)
    if target is None:
        return None
    target.state = state
    save_suggestions(suggestions)
    return target
