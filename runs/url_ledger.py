"""Per-run URL ledger: which URL ended in which funnel outcome.

Kept out of runs.json (which is loaded on every runs request) in one small
JSON file per run under the data volume. ``write`` REPLACES the file, so a
later, fuller report from the agent supersedes an earlier one. Locking and
atomic writes mirror runs/store.py.

An entry is ``{url, outcome, detail, sources: [{source, channel}]}``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from storage import atomic_write_text, data_dir, locked

# Most entries kept per run; counts elsewhere stay complete when truncated.
URL_LEDGER_CAP = 1000


def ledger_path(run_id: str) -> Path:
    """The ledger file for a run; named by a hash of the run id.

    Raises ValueError for an empty or non-string run id.
    """
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"Invalid run id {run_id!r}.")
    d = data_dir() / "run_urls"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{hashlib.sha256(run_id.encode()).hexdigest()}.json"


def write(run_id: str, entries: list[dict]) -> bool:
    """Replace the run's ledger with ``entries`` (capped); True if truncated."""
    path = ledger_path(run_id)
    truncated = len(entries) > URL_LEDGER_CAP
    kept = entries[:URL_LEDGER_CAP]
    with locked(path):
        atomic_write_text(path, json.dumps(kept, indent=2, ensure_ascii=False))
    return truncated


def _load(run_id: str) -> list[dict]:
    """Stored entries; [] when missing or malformed."""
    try:
        path = ledger_path(run_id)
    except ValueError:
        return []  # an id that can never have had a ledger written
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []


def _has_source(entry: dict, source: str, channel: str = "") -> bool:
    """Whether a source of the entry matches ``source`` (and ``channel`` if set)."""
    return any(
        s.get("source") == source and (not channel or s.get("channel") == channel)
        for s in entry.get("sources") or []
    )


def read(
    run_id: str,
    source: str = "",
    outcome: str = "",
    limit: int = 50,
    offset: int = 0,
    channel: str = "",
) -> tuple[list[dict], int]:
    """One page of the filtered ledger and the filtered total.

    ``source``, ``channel`` (with a source) and ``outcome`` narrow when non-empty; ``limit`` of 0 or less
    means no limit; a negative offset is clamped to 0.
    """
    entries = _load(run_id)
    if source:
        entries = [e for e in entries if _has_source(e, source, channel)]
    if outcome:
        entries = [e for e in entries if e.get("outcome") == outcome]
    total = len(entries)
    entries = entries[max(0, offset):]
    if limit and limit > 0:
        entries = entries[:limit]
    return entries, total
