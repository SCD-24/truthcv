"""Data shapes for tracked job applications and their owned documents.

An Application records a submission the user is pursuing and OWNS the CV and
cover letter that went out with it. A document may be absent (an application can
exist before anything is generated) and an application need not be tied to a job
posting (General/portal submissions).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Document:
    """One owned, editable+rendered document (a CV or a cover letter).

    ``source`` is the editable HTML/text the render was produced from, kept so
    the user can re-open and re-edit exactly what went out. ``pdf_filename`` /
    ``docx_filename`` are names on the data volume, downloadable via
    ``GET /api/download/{name}``.
    """

    source: str = ""
    pdf_filename: str = ""
    docx_filename: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Document | None":
        if not raw:
            return None
        return cls(
            source=raw.get("source", ""),
            pdf_filename=raw.get("pdf_filename", ""),
            docx_filename=raw.get("docx_filename", ""),
            updated_at=raw.get("updated_at", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Application:
    """A tracked job application. ``posting`` is empty for General submissions."""

    id: str = ""
    company: str = ""
    website: str = ""
    application_url: str = ""
    submitted: bool = False
    submission_type: str = "General"
    reached_out: bool = False
    to_who: str = ""
    response_received: bool = False
    method: str = ""
    posting: str = ""
    application_date: str = ""
    notes: str = ""
    cv_document: Document | None = None
    cover_letter_document: Document | None = None
    created_at: str = ""
    updated_at: str = ""

    # Fields a client may set directly on create/update (documents are managed
    # by the save-and-render routes, not by generic writes).
    EDITABLE = (
        "company",
        "website",
        "application_url",
        "submitted",
        "submission_type",
        "reached_out",
        "to_who",
        "response_received",
        "method",
        "posting",
        "application_date",
        "notes",
    )

    @classmethod
    def from_dict(cls, raw: dict) -> "Application":
        known = {f for f in cls.__dataclass_fields__ if f not in ("cv_document", "cover_letter_document")}
        values = {k: raw[k] for k in known if k in raw}
        return cls(
            **values,
            cv_document=Document.from_dict(raw.get("cv_document")),
            cover_letter_document=Document.from_dict(raw.get("cover_letter_document")),
        )

    def to_dict(self) -> dict:
        data = {f: getattr(self, f) for f in self.__dataclass_fields__}
        data["cv_document"] = self.cv_document.to_dict() if self.cv_document else None
        data["cover_letter_document"] = (
            self.cover_letter_document.to_dict() if self.cover_letter_document else None
        )
        return data


def new_id() -> str:
    """Short, filename-safe application id used in per-application filenames."""
    import uuid

    return uuid.uuid4().hex[:12]
