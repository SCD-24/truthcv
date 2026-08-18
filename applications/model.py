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
class FieldSubmitted:
    """One form field as it was actually submitted, with its provenance."""

    label: str = ""
    value: str = ""
    source: str = ""

    @classmethod
    def from_dict(cls, raw: dict | None) -> "FieldSubmitted":
        raw = raw or {}
        return cls(
            label=raw.get("label", ""),
            value=raw.get("value", ""),
            source=raw.get("source", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Confirmation:
    """Evidence that a submission actually went through."""

    text: str = ""
    confirmed_at: str = ""
    evidence: str = ""

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Confirmation":
        raw = raw or {}
        return cls(
            text=raw.get("text", ""),
            confirmed_at=raw.get("confirmed_at", ""),
            evidence=raw.get("evidence", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Glassdoor:
    """The Glassdoor check within a screening verdict."""

    rating: str | float = ""
    reviews: str | int = ""
    waiver_applied: bool = False
    note: str = ""

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Glassdoor":
        raw = raw or {}
        return cls(
            rating=raw.get("rating", ""),
            reviews=raw.get("reviews", ""),
            waiver_applied=raw.get("waiver_applied", False),
            note=raw.get("note", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Screening:
    """The pre-application filter verdicts, one field per filter."""

    entity: str = ""
    remote: str = ""
    salary: str = ""
    language: str = ""
    role_type: str = ""
    glassdoor: Glassdoor = field(default_factory=Glassdoor)

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Screening":
        raw = raw or {}
        return cls(
            entity=raw.get("entity", ""),
            remote=raw.get("remote", ""),
            salary=raw.get("salary", ""),
            language=raw.get("language", ""),
            role_type=raw.get("role_type", ""),
            glassdoor=Glassdoor.from_dict(raw.get("glassdoor")),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Attachment:
    """One file actually uploaded with the application."""

    kind: str = ""
    path: str = ""

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Attachment":
        raw = raw or {}
        return cls(kind=raw.get("kind", ""), path=raw.get("path", ""))

    def to_dict(self) -> dict:
        return asdict(self)


def flatten_notes(raw) -> str:
    """``notes`` as the single string the rest of the system declares it to be.

    Records migrated from the Jobs repo carry ``notes`` as a *list* of separate
    notes, while ``Application.notes``, ``ApplicationModel`` and the wire
    contract in web/src/api/types.ts all declare a plain string. A list reaching
    the pydantic layer unflattened fails validation and 500s the whole ledger
    (and with it the analytics view, which reads the same route), so the
    coercion lives here — on the one door every reader comes through — rather
    than in any single caller. Each note is kept as its own paragraph.
    """
    if isinstance(raw, list):
        return "\n\n".join(str(note).strip() for note in raw if str(note).strip())
    if raw is None:
        return ""
    return raw if isinstance(raw, str) else str(raw)


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
    status: str = ""
    notes: str = ""
    role: str = ""
    ats: str = ""
    capture_method: str = ""
    gaps_disclosed: list[str] = field(default_factory=list)
    fields_submitted: list[FieldSubmitted] = field(default_factory=list)
    confirmation: Confirmation = field(default_factory=Confirmation)
    screening: Screening = field(default_factory=Screening)
    attachments: list[Attachment] = field(default_factory=list)
    cv_document: Document | None = None
    cover_letter_document: Document | None = None
    created_at: str = ""
    updated_at: str = ""
    profile: str = ""

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
        "status",
        "notes",
        "role",
        "ats",
        "capture_method",
        "gaps_disclosed",
        "profile",
    )

    # Fields with dedicated (de)serialization below, excluded from the
    # generic raw-value passthrough in from_dict/to_dict.
    _NESTED = (
        "cv_document",
        "cover_letter_document",
        "fields_submitted",
        "confirmation",
        "screening",
        "attachments",
    )

    @classmethod
    def from_dict(cls, raw: dict) -> "Application":
        known = {f for f in cls.__dataclass_fields__ if f not in cls._NESTED}
        values = {k: raw[k] for k in known if k in raw}
        if "notes" in values:
            values["notes"] = flatten_notes(values["notes"])
        return cls(
            **values,
            cv_document=Document.from_dict(raw.get("cv_document")),
            cover_letter_document=Document.from_dict(raw.get("cover_letter_document")),
            fields_submitted=[
                FieldSubmitted.from_dict(f) for f in raw.get("fields_submitted") or []
            ],
            confirmation=Confirmation.from_dict(raw.get("confirmation")),
            screening=Screening.from_dict(raw.get("screening")),
            attachments=[Attachment.from_dict(a) for a in raw.get("attachments") or []],
        )

    def to_dict(self) -> dict:
        data = {
            f: getattr(self, f) for f in self.__dataclass_fields__ if f not in self._NESTED
        }
        data["gaps_disclosed"] = list(self.gaps_disclosed)
        data["cv_document"] = self.cv_document.to_dict() if self.cv_document else None
        data["cover_letter_document"] = (
            self.cover_letter_document.to_dict() if self.cover_letter_document else None
        )
        data["fields_submitted"] = [f.to_dict() for f in self.fields_submitted]
        data["confirmation"] = self.confirmation.to_dict()
        data["screening"] = self.screening.to_dict()
        data["attachments"] = [a.to_dict() for a in self.attachments]
        return data


def new_id() -> str:
    """Short, filename-safe application id used in per-application filenames."""
    import uuid

    return uuid.uuid4().hex[:12]
