"""Wire models for tracked applications and their documents."""

from __future__ import annotations

from pydantic import Field

from .common import _Camel
from .cv import BlockedClaimModel


class ApplicationDocument(_Camel):
    """One owned document (CV or cover letter): its editable source and the
    per-application files it rendered to, as download URLs."""

    source: str = ""
    pdf_url: str | None = None
    docx_url: str | None = None
    updated_at: str = ""


class FieldSubmittedModel(_Camel):
    """One form field as it was actually submitted, with its provenance."""

    label: str = ""
    value: str = ""
    source: str = ""


class ConfirmationModel(_Camel):
    """Evidence that a submission actually went through."""

    text: str = ""
    confirmed_at: str = ""
    evidence: str = ""


class ApplicationScreeningModel(_Camel):
    """The pre-application filter verdicts recorded on a tracked application.

    Distinct from ScreeningModel further down this file, which is the wire
    shape for the separate screenings-queue record (GET/POST /screenings).

    These are facts about a POSTING (remote policy, salary, language, role
    type), not about a company — company-level claims (employing entity,
    employer-review figures) live in CompanyFindingModel / companyresearch
    instead, where they carry a source and an as-of date.
    """

    remote: str = ""
    salary: str = ""
    language: str = ""
    role_type: str = ""


class AttachmentModel(_Camel):
    """One file actually uploaded with the application."""

    kind: str = ""
    path: str = ""


class ApplicationModel(_Camel):
    """A tracked job application. `posting` is empty for General submissions;
    the document fields are absent until something has been generated for it."""

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
    fields_submitted: list[FieldSubmittedModel] = Field(default_factory=list)
    confirmation: ConfirmationModel = Field(default_factory=ConfirmationModel)
    screening: ApplicationScreeningModel = Field(default_factory=ApplicationScreeningModel)
    attachments: list[AttachmentModel] = Field(default_factory=list)
    gaps_disclosed: list[str] = Field(default_factory=list)
    profile: str = ""
    screening_id: str = ""
    cv_document: ApplicationDocument | None = None
    cover_letter_document: ApplicationDocument | None = None
    created_at: str = ""
    updated_at: str = ""


class ApplicationCreate(_Camel):
    """Client-supplied fields for a new application (all optional; documents are
    never set here — they are attached via the save-and-render routes)."""

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
    gaps_disclosed: list[str] = Field(default_factory=list)
    profile: str = ""


class ApplicationUpdate(_Camel):
    """A partial patch of an application's editable fields (None = leave as-is)."""

    company: str | None = None
    website: str | None = None
    application_url: str | None = None
    submitted: bool | None = None
    submission_type: str | None = None
    reached_out: bool | None = None
    to_who: str | None = None
    response_received: bool | None = None
    method: str | None = None
    posting: str | None = None
    application_date: str | None = None
    status: str | None = None
    notes: str | None = None
    role: str | None = None
    ats: str | None = None
    capture_method: str | None = None
    gaps_disclosed: list[str] | None = None
    profile: str | None = None


class SaveCvRequest(_Camel):
    """Edited CV content to guardrail-check, render, and save on an application."""

    html: str


class SaveCoverLetterRequest(_Camel):
    """Edited cover-letter text to guardrail-check, render, and save."""

    text: str


class SaveDocumentResult(_Camel):
    """Response of a save-and-render route: blocked state or the saved document."""

    blocked: bool = False
    unverifiable: list[str] = Field(default_factory=list)
    blocked_claims: list[BlockedClaimModel] = Field(default_factory=list)
    application: ApplicationModel | None = None
    # True when the guardrail passed and the source was saved, but the rendering
    # backend (WeasyPrint/pandoc) produced neither a PDF nor a DOCX — so the
    # document is attached but its download links are null. NOT a save failure.
    render_unavailable: bool = False


class ApplicationListResponse(_Camel):
    """GET /api/applications/page: one page of applications, server-sorted.

    ``total`` is the count across all pages, not this page's length — the
    client needs it to know how many pages exist, and it cannot be derived
    from a capped page. ``limit``/``offset`` are echoed back so a client that
    let the server apply its default knows what it actually got. ``sort`` and
    ``direction`` are echoed to confirm which sorting was applied.
    """

    applications: list[ApplicationModel]
    total: int = 0
    limit: int = 0
    offset: int = 0
    sort: str = "date"
    direction: str = "desc"
