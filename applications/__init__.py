"""Application Tracker: persistent job-application records and their documents.

Each Application records a submission (company, website, status flags, contact,
method) and OWNS the CV and cover letter that went out with it. Applications may
be General (no posting) or tied to a specific posting, and may exist before any
document is generated.
"""

from __future__ import annotations

from .model import Application, Document, new_id
from .store import (
    cover_letter_filenames,
    create,
    cv_filenames,
    delete,
    delete_documents,
    get,
    load_all,
    save_cover_letter_document,
    save_cv_document,
    update,
)

__all__ = [
    "Application",
    "Document",
    "new_id",
    "load_all",
    "get",
    "create",
    "update",
    "delete",
    "delete_documents",
    "save_cv_document",
    "save_cover_letter_document",
    "cv_filenames",
    "cover_letter_filenames",
]
