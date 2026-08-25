"""Persistence for tracked applications against the ./data volume.

Mirrors truth/store.py: one JSON file on the shared data volume, written
written through ``datafile``, which serialises each load-modify-write against
an advisory lock — the agent records applications over MCP into the same `app`
process the operator's browser writes from, so concurrent writers are routine.
The store also owns the lifecycle of each application's rendered document files.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from truth.store import data_dir

from .model import (
    Application,
    Attachment,
    Confirmation,
    Document,
    FieldSubmitted,
    Screening,
    new_id,
)


from datafile import atomic_write_text, locked


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
    """Persist the full list to applications.json.

    Callers must already hold ``locked(applications_path())``; this writes the
    list it is given and reconciles nothing.
    """
    atomic_write_text(
        applications_path(),
        json.dumps([a.to_dict() for a in apps], indent=2, ensure_ascii=False),
    )


def get(app_id: str) -> Application | None:
    """The application with this id, or None."""
    return next((a for a in load_all() if a.id == app_id), None)


def _create_locked(fields: dict, apps: list[Application]) -> Application:
    """Mint, populate, append, and persist a new application into ``apps``.

    Callers must already hold ``locked(applications_path())`` and pass the list
    they loaded under that lock: this mints the id and timestamps, applies the
    editable fields, appends the record to ``apps``, and writes the list once.
    Returns the created application.
    """
    now = _now()
    app = Application(id=new_id(), created_at=now, updated_at=now)
    _apply_editable(app, fields)
    apps.append(app)
    _write_all(apps)
    return app


def create(fields: dict) -> Application:
    """Create a new application from client-supplied editable fields."""
    with locked(applications_path()):
        apps = load_all()
        app = _create_locked(fields, apps)
    return app


def find_by_screening(screening_id: str) -> Application | None:
    """The first application tied to this screening_id, or None.

    A plain read, no lock (mirrors ``get``). An empty ``screening_id`` never
    matches a real record, so return None without loading anything.
    """
    if not screening_id:
        return None
    return next((a for a in load_all() if a.screening_id == screening_id), None)


def create_for_screening(fields: dict, screening_id: str) -> tuple[Application, bool]:
    """Create an application for a screening, at most once per screening_id.

    Returns ``(application, created)``. With no ``screening_id`` there is
    nothing to key on, so this falls back to an unconditional ``create`` and
    always reports ``created=True``.

    Otherwise the existence check and the write share one lock — like
    ``screening.store.claim_for_apply`` — which is what makes it idempotent:
    two concurrent callers racing on the same ``screening_id`` cannot both find
    it absent and both create a row. The loser sees the winner's record and gets
    ``(existing, False)`` without writing anything.
    """
    if not screening_id:
        return create(fields), True
    with locked(applications_path()):
        apps = load_all()
        existing = next((a for a in apps if a.screening_id == screening_id), None)
        if existing is not None:
            return existing, False
        fields = {**fields, "screening_id": screening_id}
        app = _create_locked(fields, apps)
    return app, True


def update(app_id: str, patch: dict) -> Application | None:
    """Patch an application's editable fields; returns the updated record."""
    with locked(applications_path()):
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
    with locked(applications_path()):
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
    with locked(applications_path()):
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


# --- Structured evidence fields ------------------------------------------------

def _persist_field(app_id: str, attr: str, value) -> Application | None:
    """Load, set one structured field, stamp updated_at, and atomically persist."""
    with locked(applications_path()):
        apps = load_all()
        app = next((a for a in apps if a.id == app_id), None)
        if app is None:
            return None
        setattr(app, attr, value)
        app.updated_at = _now()
        _write_all(apps)
    return app


def save_fields_submitted(app_id: str, fields_submitted) -> Application | None:
    """Replace the as-submitted form-field evidence for an application."""
    values = [
        f if isinstance(f, FieldSubmitted) else FieldSubmitted.from_dict(f)
        for f in fields_submitted or []
    ]
    return _persist_field(app_id, "fields_submitted", values)


def save_confirmation(app_id: str, confirmation) -> Application | None:
    """Replace the submission-confirmation evidence for an application."""
    value = (
        confirmation
        if isinstance(confirmation, Confirmation)
        else Confirmation.from_dict(confirmation)
    )
    return _persist_field(app_id, "confirmation", value)


def save_screening(app_id: str, screening) -> Application | None:
    """Replace the pre-application screening verdicts for an application."""
    value = screening if isinstance(screening, Screening) else Screening.from_dict(screening)
    return _persist_field(app_id, "screening", value)


def save_attachments(app_id: str, attachments) -> Application | None:
    """Replace the actually-uploaded attachment evidence for an application."""
    values = [
        a if isinstance(a, Attachment) else Attachment.from_dict(a)
        for a in attachments or []
    ]
    return _persist_field(app_id, "attachments", values)


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
