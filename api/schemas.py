"""Request/response models with camelCase JSON aliases.

Python stays snake_case internally; the wire contract matches exactly what the
frontend client (web/src/api/types.ts) expects.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

_RUN_AT_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
_RUN_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


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


class AnswersModel(_Camel):
    """Canonical ATS screening answers — GET/PUT /api/profile/answers wire shape.

    Mirrors every field of truth.answers.Answers (the runbook-transcribed
    canonical answers plus canonical_cv_asset_id) so GET/PUT round-trips the
    full record instead of silently dropping fields pydantic doesn't know
    about.
    """

    phone: str = ""
    work_authorisation: str = ""
    salary_expectation: str = ""
    notice_period: str = ""
    location_preference: str = ""
    canonical_cv_asset_id: str | None = None
    name: str = ""
    email: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""
    requires_sponsorship: str = ""
    authorized_non_german_country: str = ""
    languages: str = ""
    highest_relevant_degree: str = ""
    other_degree: str = ""
    cs_degree: str = ""
    gpa: str = ""
    gender: str = ""
    years_of_experience: str = ""
    current_role: str = ""
    how_did_you_hear: str = ""


class AnswersUpdate(_Camel):
    """Partial PUT /api/profile/answers body — every field optional.

    Mirrors AnswersModel field-for-field, but all fields default to None so
    the route can tell "the client didn't send this field" (stays None, and
    is excluded via `model_dump(exclude_unset=True)`) apart from "the client
    sent it" — including an explicit empty string, which IS applied. This is
    what lets PUT merge only the supplied fields onto the existing stored
    answers instead of clobbering everything else back to blank/default.
    """

    phone: str | None = None
    work_authorisation: str | None = None
    salary_expectation: str | None = None
    notice_period: str | None = None
    location_preference: str | None = None
    canonical_cv_asset_id: str | None = None
    name: str | None = None
    email: str | None = None
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None
    requires_sponsorship: str | None = None
    authorized_non_german_country: str | None = None
    languages: str | None = None
    highest_relevant_degree: str | None = None
    other_degree: str | None = None
    cs_degree: str | None = None
    gpa: str | None = None
    gender: str | None = None
    years_of_experience: str | None = None
    current_role: str | None = None
    how_did_you_hear: str | None = None


class AgentConfigModel(_Camel):
    """GET /api/agent/config response: enabled flag, blocklist, and schedule."""

    enabled: bool = True
    blocked_companies: list[str] = Field(default_factory=list)
    run_at: list[str] = Field(default_factory=lambda: ["09:00", "15:00"])
    run_days: list[str] = Field(
        default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"]
    )


class AgentConfigUpdate(_Camel):
    """Partial PUT /api/agent/config body — every field optional.

    Mirrors AnswersUpdate's merge semantics: omitted fields stay None and are
    excluded via `model_dump(exclude_unset=True)`, so the route only applies
    the fields the client actually sent.
    """

    enabled: bool | None = None
    blocked_companies: list[str] | None = None
    run_at: list[str] | None = None
    run_days: list[str] | None = None

    @field_validator("blocked_companies")
    @classmethod
    def _strip_and_drop_empties(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return [s.strip() for s in v if s.strip()]

    @field_validator("run_at")
    @classmethod
    def _validate_run_at(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if not v:
            raise ValueError("runAt must not be empty")
        for t in v:
            if not _RUN_AT_RE.match(t):
                raise ValueError(f"invalid time {t!r}, expected HH:MM")
        return v

    @field_validator("run_days")
    @classmethod
    def _validate_run_days(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if not v:
            raise ValueError("runDays must not be empty")
        deduped: list[str] = []
        for d in v:
            if d not in _RUN_DAYS:
                raise ValueError(f"invalid day {d!r}, expected one of {sorted(_RUN_DAYS)}")
            if d not in deduped:
                deduped.append(d)
        return deduped


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
    status: str = ""
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
    status: str = ""
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
    status: str | None = None
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


class ScreeningModel(_Camel):
    """A tracked job-screening record: the wire shape for GET/POST /screenings."""

    id: str = ""
    company: str = ""
    role: str = ""
    url: str = ""
    screened_date: str = ""
    verdict: str = ""
    failing_criterion: str = ""
    reason: str = ""
    cooldown_expires: str = ""
    source: str = ""
    created_at: str = ""
    updated_at: str = ""


class ScreeningCreate(_Camel):
    """Client-supplied fields for a new screening record."""

    company: str = ""
    role: str = ""
    url: str = ""
    screened_date: str = ""
    verdict: str = ""
    failing_criterion: str = ""
    reason: str = ""
    cooldown_expires: str = ""
    source: str = ""


class CooldownResult(_Camel):
    """Whether a company (optionally role) is currently in cooldown."""

    in_cooldown: bool
    expires: str | None = None
    blocked: bool = False


class ConnectionStatus(_Camel):
    """One catalog card's connection state — never carries token material."""

    provider: str
    label: str
    modes: list[str]
    subscription_connected: bool = False
    api_key_connected: bool = False
    auth_mode: str = ""
    expires_at: float | None = None
    connected_at: float | None = None


class ConnectionList(_Camel):
    """GET /api/auth/status response: one ConnectionStatus per catalog card."""

    encryption_available: bool
    connections: list[ConnectionStatus] = []


class StartLoginResult(_Camel):
    flow: str
    auth_url: str | None = None
    user_code: str | None = None
    verification_uri: str | None = None


class CompleteLoginRequest(_Camel):
    code: str


class ApiKeyRequest(_Camel):
    api_key: str | None = None
    base_url: str | None = None
    bearer: str | None = None


class ConnectionTestRequest(_Camel):
    model: str | None = None
