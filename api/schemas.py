"""Request/response models with camelCase JSON aliases.

Python stays snake_case internally; the wire contract matches exactly what the
frontend client (web/src/api/types.ts) expects.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class BulletModel(_Camel):
    id: str
    value: str
    source: str = "linkedin-pdf"


class ExperienceModel(_Camel):
    id: str
    role: str = ""
    company: str = ""
    start: str = ""
    end: str = ""
    source: str = "linkedin-pdf"
    bullets: list[BulletModel] = Field(default_factory=list)


class EducationModel(_Camel):
    id: str
    degree: str = ""
    school: str = ""
    start: str = ""
    end: str = ""
    source: str = "linkedin-pdf"


class SkillModel(_Camel):
    id: str
    value: str
    source: str = "linkedin-pdf"


class LinkModel(_Camel):
    label: str = ""
    url: str = ""


class ProfileModel(_Camel):
    """Personal header. Identity fields are guardrail-exempt; summary is a claim."""

    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[LinkModel] = Field(default_factory=list)
    summary: str = ""


class TruthDoc(_Camel):
    """The structured truth — GET /truth response and PUT /truth request body."""

    experiences: list[ExperienceModel] = Field(default_factory=list)
    education: list[EducationModel] = Field(default_factory=list)
    skills: list[SkillModel] = Field(default_factory=list)
    profile: ProfileModel = Field(default_factory=ProfileModel)


class TailorRequest(_Camel):
    posting: str


class InferenceModel(_Camel):
    id: str
    claim: str
    rationale: str = ""
    experience_id: str = ""


class TailorResult(_Camel):
    keywords: list[str]
    inferences: list[InferenceModel]


class ApprovedInference(_Camel):
    """A user-approved inference carrying its (possibly edited) claim + target."""

    id: str
    claim: str
    experience_id: str = ""


class ConfirmInferencesRequest(_Camel):
    """Approved inferences to write as user-confirmed bullets.

    `approved` carries the user-edited claim text and target experience and takes
    precedence when present. `approved_ids` is the deprecated fallback: it writes
    each id's *original* draft claim (looked up server-side) verbatim.
    """

    approved: list[ApprovedInference] = Field(default_factory=list)
    approved_ids: list[str] = Field(default_factory=list)


class AtsWarning(_Camel):
    code: str
    message: str


class BlockedClaimModel(_Camel):
    """A whole draft bullet/line that tripped the guardrail, offered for
    per-claim approve/deny on the download step."""

    claim_id: str
    experience_id: str = ""
    text: str
    tokens: list[str] = Field(default_factory=list)


class RenderApprovals(_Camel):
    """Render-scoped decisions on blocked claims. Never persisted to truth.yaml."""

    approved_claim_ids: list[str] = Field(default_factory=list)
    denied_claim_ids: list[str] = Field(default_factory=list)


class RenderRequest(_Camel):
    approvals: RenderApprovals | None = None
    # When present, rendered output is saved as this application's owned CV
    # document (per-application filenames) instead of the shared scratch file.
    application_id: str | None = None


class RenderResult(_Camel):
    blocked: bool
    unverifiable: list[str] = Field(default_factory=list)
    blocked_claims: list[BlockedClaimModel] = Field(default_factory=list)
    ats_warnings: list[AtsWarning] = Field(default_factory=list)
    pdf_url: str | None = None
    docx_url: str | None = None
    # The rendered CV HTML, so the UI can pre-fill an editor with what shipped.
    html: str | None = None
    # True when attached to an application and the source was saved, but neither
    # a PDF nor a DOCX could be produced (render backend unavailable).
    render_unavailable: bool = False


class SettingsStatus(_Camel):
    encryption_available: bool
    active_provider: str
    model: str = ""
    anthropic_key_set: bool = False
    openai_key_set: bool = False
    ollama_host: str = ""


class SettingsUpdate(_Camel):
    active_provider: str
    api_key: str | None = None
    model: str | None = None
    ollama_host: str | None = None


class TestResult(_Camel):
    ok: bool
    detail: str = ""


class ModelInfo(_Camel):
    id: str
    label: str


class ModelList(_Camel):
    models: list[ModelInfo] = []


class ProfileStatus(_Camel):
    has_profile: bool


class CoverLetterApprovals(_Camel):
    """Generation-scoped decisions on blocked cover-letter claims. Approved
    claims are allowed for that one generation only; never persisted to
    truth.yaml (mirrors RenderApprovals)."""

    approved_claim_ids: list[str] = Field(default_factory=list)
    denied_claim_ids: list[str] = Field(default_factory=list)


class CoverLetterRequest(_Camel):
    tone: str = "Professional"
    length: str = "Standard"
    # When present, the letter is saved as this application's owned document.
    application_id: str | None = None
    # Decisions on claims a previous attempt blocked, so the user can approve
    # and continue (or decline) instead of dead-ending.
    approvals: CoverLetterApprovals | None = None


class CoverLetterResult(_Camel):
    blocked: bool
    unverifiable: list[str] = Field(default_factory=list)
    # Blocked claims grouped by source sentence (same shape as RenderResult), so
    # the UI can offer per-claim approve/decline instead of a loose token blob.
    blocked_claims: list[BlockedClaimModel] = Field(default_factory=list)
    pdf_url: str | None = None
    docx_url: str | None = None
    # The generated letter text, so the UI can pre-fill an editor with it.
    text: str | None = None
    # True when attached to an application and the source was saved, but neither
    # a PDF nor a DOCX could be produced (render backend unavailable).
    render_unavailable: bool = False


class ApplicationDocument(_Camel):
    """One owned document (CV or cover letter): its editable source and the
    per-application files it rendered to, as download URLs."""

    source: str = ""
    pdf_url: str | None = None
    docx_url: str | None = None
    updated_at: str = ""


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
    notes: str = ""
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
    notes: str = ""


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
    notes: str | None = None


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
