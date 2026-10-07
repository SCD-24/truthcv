from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterable
from pathlib import Path

from storage import atomic_write_text, data_dir

from .model import GmailSuggestion, GmailSyncState


#: Serializes load->save cycles on the suggestions file across threads.
_SUGGESTIONS_LOCK = threading.Lock()


#: Dismissed suggestions are deleted once dismissed longer than 30 days.
DISMISSED_RETENTION_S = 30 * 24 * 60 * 60


def sync_state_path() -> Path:
    return data_dir() / "gmail_sync.json"


def suggestions_path() -> Path:
    return data_dir() / "gmail_suggestions.json"


def _write_json(path: Path, payload) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))


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
    """Set one suggestion's state under the store lock; None if the id is unknown."""
    with _SUGGESTIONS_LOCK:
        suggestions = load_suggestions()
        target = next((item for item in suggestions if item.id == suggestion_id), None)
        if target is None:
            return None
        target.state = state
        save_suggestions(suggestions)
        return target


def _prune_dismissed(items: list[GmailSuggestion], now: float) -> tuple[list[GmailSuggestion], bool]:
    """Drop dismissed items older than the retention window.

    Legacy dismissed items (dismissed_at == 0) are stamped with `now` and kept.
    Returns (kept, changed).
    """
    kept: list[GmailSuggestion] = []
    changed = False
    for item in items:
        if item.state == "dismissed":
            if item.dismissed_at > 0 and now - item.dismissed_at > DISMISSED_RETENTION_S:
                changed = True
                continue
            if item.dismissed_at == 0:
                item.dismissed_at = now
                changed = True
        kept.append(item)
    return kept, changed


def dismiss_suggestions(ids: Iterable[str], now: float | None = None) -> int:
    """Mark the given pending suggestions dismissed and prune expired ones; return how many were dismissed."""
    wanted = set(ids)
    if now is None:
        now = time.time()
    with _SUGGESTIONS_LOCK:
        suggestions = load_suggestions()
        dismissed = 0
        for item in suggestions:
            if item.id in wanted and item.state == "pending":
                item.state = "dismissed"
                item.dismissed_at = now
                dismissed += 1
        kept, pruned = _prune_dismissed(suggestions, now)
        if dismissed or pruned:
            save_suggestions(kept)
        return dismissed


def merge_new_suggestions(new_items: list[GmailSuggestion], now: float | None = None) -> list[GmailSuggestion]:
    """Prune expired dismissed items, then append items whose id is not on disk yet; on-disk state wins."""
    if now is None:
        now = time.time()
    with _SUGGESTIONS_LOCK:
        merged, _ = _prune_dismissed(load_suggestions(), now)
        present = {item.id for item in merged}
        for item in new_items:
            if item.id not in present:
                present.add(item.id)
                merged.append(item)
        save_suggestions(merged)
        return merged
