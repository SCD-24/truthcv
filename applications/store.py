"""Persistence for tracked applications against the ./data volume.

Mirrors truth/store.py: one JSON file on the shared data volume, written
atomically (.tmp then replace) so a crash mid-write can never corrupt the list.
The store also owns the lifecycle of each application's rendered document files.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from truth.store import data_dir

from .model import Application, Document, new_id


def applications_path() -> Path:
    return data_dir() / "applications.json"


def _now() -> str:
    """UTC ISO-8601 timestamp; single source so created/updated stay consistent."""
    return datetime.now(timezone.utc).isoformat()


def load_all() -> list[Application]:
    """Every tracked application; empty list if the file is missing or invalid.

    Fails safe on a malformed file (returns []) so a hand-edited or partially
    written JSON never crashes the app on startup.
    """
    p = applications_path()
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    return [Application.from_dict(item) for item in raw if isinstance(item, dict)]


def _write_all(apps: list[Application]) -> None:
    """Atomically persist the full list to applications.json."""
    p = applications_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps([a.to_dict() for a in apps], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(p)


def get(app_id: str) -> Application | None:
    """The application with this id, or None."""
    return next((a for a in load_all() if a.id == app_id), None)


def create(fields: dict) -> Application:
    """Create a new application from client-supplied editable fields."""
    now = _now()
    app = Application(id=new_id(), created_at=now, updated_at=now)
    _apply_editable(app, fields)
    apps = load_all()
    apps.append(app)
    _write_all(apps)
    return app


def update(app_id: str, patch: dict) -> Application | None:
    """Patch an application's editable fields; returns the updated record."""
    apps = load_all()
    app = next((a for a in apps if a.id == app_id), None)
    if app is None:
        return None
    _apply_editable(app, patch)
    app.updated_at = _now()
    _write_all(apps)
    return app


def delete(app_id: str) -> bool:
    """Remove an application and its owned document files. True if it existed."""
    apps = load_all()
    app = next((a for a in apps if a.id == app_id), None)
    if app is None:
        return False
    delete_documents(app)
    _write_all([a for a in apps if a.id != app_id])
    return True


def _apply_editable(app: Application, fields: dict) -> None:
    """Copy only whitelisted fields; documents are managed by save_* helpers."""
    for key in Application.EDITABLE:
        if key in fields and fields[key] is not None:
            setattr(app, key, fields[key])


# --- Owned document files ------------------------------------------------------

def cv_filenames(app_id: str) -> tuple[str, str]:
    """Per-application CV filenames (pdf, docx) on the data volume."""
    return f"cv_{app_id}.pdf", f"cv_{app_id}.docx"


def cover_letter_filenames(app_id: str) -> tuple[str, str]:
    """Per-application cover-letter filenames (pdf, docx) on the data volume."""
    return f"cover_letter_{app_id}.pdf", f"cover_letter_{app_id}.docx"


def _persist_document(app_id: str, attr: str, doc: Document) -> Application | None:
    apps = load_all()
    app = next((a for a in apps if a.id == app_id), None)
    if app is None:
        return None
    doc.updated_at = _now()
    setattr(app, attr, doc)
    app.updated_at = doc.updated_at
    _write_all(apps)
    return app


def save_cv_document(app_id: str, source: str) -> Application | None:
    """Attach a saved CV (editable source + its per-application filenames)."""
    pdf, docx = cv_filenames(app_id)
    return _persist_document(app_id, "cv_document", Document(source, pdf, docx))


def save_cover_letter_document(app_id: str, source: str) -> Application | None:
    """Attach a saved cover letter (source + its per-application filenames)."""
    pdf, docx = cover_letter_filenames(app_id)
    return _persist_document(
        app_id, "cover_letter_document", Document(source, pdf, docx)
    )


def delete_documents(app: Application) -> None:
    """Remove any rendered files this application owns from the data volume."""
    names = [*cv_filenames(app.id), *cover_letter_filenames(app.id)]
    for name in names:
        path = data_dir() / name
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
