"""One-shot startup purge of legacy 'unreadable' screening records.

Unreadable screenings no longer queue for approval; records created before
that change sit in the queue as noise. This deletes them once, guarded by a
marker file on the data volume.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone

from applications import store as applications_store
from storage import atomic_write_text, data_dir

from . import store

_MARKER = ".purge_unreadable_screenings.v1.done"
_BACKUP = "screenings.pre-unreadable-purge.bak.json"
_PROTECTED_APPROVALS = frozenset({"applied", "approved"})


def _backup_once() -> str:
    """Atomically copy screenings.json to the backup path unless it exists."""
    target = data_dir() / _BACKUP
    if not target.exists():
        tmp = target.with_suffix(".tmp")
        shutil.copyfile(store.screenings_path(), tmp)
        os.replace(tmp, target)
    return str(target)


def purge_unreadable_once() -> dict | None:
    """Delete unreadable screenings exactly once; None if already done.

    Records the operator approved or applied, and records an application
    references, are protected and kept. A backup of screenings.json is taken
    atomically (never overwritten) before deleting. The marker is written
    last, only after deletion succeeded.

    Returns:
        ``{"deleted", "protected", "backup"}`` or None when the marker exists.
    """
    marker = data_dir() / _MARKER
    if marker.exists():
        return None
    unreadable = [s for s in store.load_all() if s.screening_blocker == "unreadable"]
    referenced = {a.screening_id for a in applications_store.load_all() if a.screening_id}
    doomed = [
        s.id
        for s in unreadable
        if s.approval not in _PROTECTED_APPROVALS and s.id not in referenced
    ]
    protected = len(unreadable) - len(doomed)
    backup = None
    if doomed:
        backup = _backup_once()
        store.delete_many(doomed)
    atomic_write_text(marker, datetime.now(timezone.utc).isoformat())
    return {"deleted": len(doomed), "protected": protected, "backup": backup}
