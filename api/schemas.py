"""Request/response models with camelCase JSON aliases.

Python stays snake_case internally; the wire contract matches exactly what the
frontend client (web/src/api/types.ts) expects.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from agentconfig.store import AgentConfig
from screening.role import normalize_role_title, validate_role_title
from screening.url import validate_posting_url

_RUN_AT_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
_RUN_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class BulletModel(_Camel):
    id: str
    value: str
    source: str = "uploaded-cv"


class ExperienceModel(_Camel):
    id: str
    role: str = ""
    company: str = ""
    start: str = ""
    end: str = ""
    source: str = "uploaded-cv"
    bullets: list[BulletModel] = Field(default_factory=list)


class EducationModel(_Camel):
    id: str
    degree: str = ""
    school: str = ""
    start: str = ""
    end: str = ""
    source: str = "uploaded-cv"


class SkillModel(_Camel):
    id: str
    value: str
    source: str = "uploaded-cv"


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
    effort_levels: list[str] = Field(default_factory=list)


class ModelList(_Camel):
    models: list[ModelInfo] = []


class ProfileStatus(_Camel):
    has_profile: bool


class OnboardingState(_Camel):
    """GET/PUT /api/onboarding response: first-run onboarding progress."""

    provider_done: bool
    has_profile: bool
    cv_reviewed_at: str | None = None
    tour_seen_at: str | None = None
    complete: bool


class OnboardingUpdate(_Camel):
    """Partial PUT /api/onboarding body — only the sent fields are merged."""

    cv_reviewed_at: str | None = None
    tour_seen_at: str | None = None


class AnswersModel(_Camel):
    """Canonical ATS screening answers — GET/PUT /api/profile/answers wire shape.

    Mirrors every field of truth.answers.Answers (the runbook-transcribed
    canonical answers plus canonical_cv_asset_id) so GET/PUT round-trips the
    full record instead of silently dropping fields pydantic doesn't know
    about.
    """

    phone: str = ""
    work_authorisation: str = ""
    notice_period: str = ""
    location_preference: str = ""
    canonical_cv_asset_id: str | None = None
    name: str = ""
    email: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""
    requires_sponsorship: str = ""
    work_authorisation_note: str = ""
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
    notice_period: str | None = None
    location_preference: str | None = None
    canonical_cv_asset_id: str | None = None
    name: str | None = None
    email: str | None = None
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None
    requires_sponsorship: str | None = None
    work_authorisation_note: str | None = None
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


class JobProfileModel(_Camel):
    """Job search profile with search criteria and requirements."""

    name: str = ""
    enabled: bool = True
    keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    preferred_sources: list[str] = Field(default_factory=list)
    remote_model: str | None = None
    employment_country: str | None = None
    eor_allowed: bool | None = None
    require_entity_verification: bool = True
    salary_floor: int | None = None
    salary_ask_min: int | None = None
    salary_ask_max: int | None = None
    # User-chosen currency code; None means the user has not configured one
    # and no default currency may be assumed.
    currency: str | None = None
    working_language: str | None = None
    glassdoor_min: float | None = None
    glassdoor_min_reviews: int | None = None
    accepted_role_types: list[str] = Field(default_factory=list)
    rejected_role_types: list[str] = Field(default_factory=list)

    @field_validator("salary_floor", "salary_ask_min", "salary_ask_max")
    @classmethod
    def _validate_salary_values(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("salary values must be > 0")
        return v

    @field_validator("glassdoor_min")
    @classmethod
    def _validate_glassdoor_min(cls, v: float | None) -> float | None:
        if v is not None and (v < 0 or v > 5):
            raise ValueError("glassdoor_min must be between 0 and 5")
        return v

    @field_validator("glassdoor_min_reviews")
    @classmethod
    def _validate_glassdoor_min_reviews(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("glassdoor_min_reviews must be >= 0")
        return v

    @field_validator("keywords", "locations", "preferred_sources", "accepted_role_types", "rejected_role_types", mode="before")
    @classmethod
    def _split_comma_delimited_lists(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            return [s.strip() for s in v if isinstance(s, str) and s.strip()]
        return v


class CompanyBoardModel(_Camel):
    """Resolved company board entry (response-only)."""

    company: str
    careers_url: str
    ats: str = ""
    status: str = "ok"
    resolved_at: str = ""


class SearchQueryModel(_Camel):
    """Composed search query (response-only)."""

    profile: str
    source: str
    query: str
    url: str


class AgentConfigModel(_Camel):
    """GET /api/agent/config response: enabled flag, blocklist, schedule, job profiles, and resolved boards."""

    mode: str = "full"
    # Derived server-side from mode; present so existing readers need no change.
    enabled: bool = True
    blocked_companies: list[str] = Field(default_factory=list)
    run_at: list[str] = Field(default_factory=lambda: ["09:00", "15:00"])
    run_days: list[str] = Field(
        default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"]
    )
    profiles: list[JobProfileModel] = Field(default_factory=list)
    target_companies: list[str] = Field(default_factory=list)
    cooldown_days: int | None = None
    cooldown_days_same_role: int | None = None
    cooldown_days_same_company: int | None = None
    max_applications_per_run: int | None = None
    max_posting_age_days: int | None = None
    company_boards: list[CompanyBoardModel] = Field(default_factory=list)
    search_queries: list[SearchQueryModel] = Field(default_factory=list)


class AgentConfigUpdate(_Camel):
    """Partial PUT /api/agent/config body — every field optional.

    Mirrors AnswersUpdate's merge semantics: omitted fields stay None and are
    excluded via `model_dump(exclude_unset=True)`, so the route only applies
    the fields the client actually sent.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=to_camel)

    mode: str | None = None
    blocked_companies: list[str] | None = None
    run_at: list[str] | None = None
    run_days: list[str] | None = None
    profiles: list[JobProfileModel] | None = None
    target_companies: list[str] | None = None
    cooldown_days: int | None = None
    cooldown_days_same_role: int | None = None
    cooldown_days_same_company: int | None = None
    max_applications_per_run: int | None = None
    max_posting_age_days: int | None = None

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in AgentConfig.MODES:
            raise ValueError(f"Unknown mode '{v}'. Expected one of {', '.join(AgentConfig.MODES)}.")
        return v

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

    @field_validator("target_companies", mode="before")
    @classmethod
    def _validate_target_companies(cls, v: list[str] | str | None) -> list[str] | None:
        if v is None:
            return v
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            return [s.strip() for s in v if isinstance(s, str) and s.strip()]
        return v

    @field_validator("cooldown_days", "cooldown_days_same_role", "cooldown_days_same_company")
    @classmethod
    def _validate_cooldown_days(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 0:
            raise ValueError("cooldown days must be >= 0 (0 disables the window)")
        return v

    @field_validator("max_applications_per_run")
    @classmethod
    def _validate_max_applications_per_run(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 1:
            raise ValueError("maxApplicationsPerRun must be >= 1")
        return v

    @field_validator("max_posting_age_days")
    @classmethod
    def _validate_max_posting_age_days(cls, v: int | None) -> int | None:
        """0 is meaningful here — it disables the window — so only negatives fail.

        The upper bound stops a typo ("3650") from reading as a deliberate
        choice to consider year-old postings.
        """
        if v is None:
            return v
        if v < 0:
            raise ValueError("maxPostingAgeDays must be >= 0 (0 disables the window)")
        if v > 365:
            raise ValueError("maxPostingAgeDays must be <= 365")
        return v

    @field_validator("profiles")
    @classmethod
    def _validate_profiles(cls, v: list[JobProfileModel] | None) -> list[JobProfileModel] | None:
        if v is None:
            return v
        # Check for non-empty unique names and salary ordering
        names_seen = set()
        for profile in v:
            name = profile.name.strip()
            if not name:
                raise ValueError("profile name must not be empty")
            if name in names_seen:
                raise ValueError(f"duplicate profile name: {name!r}")
            names_seen.add(name)
            # Check salary ordering: floor <= ask_min <= ask_max
            if profile.salary_floor is not None and profile.salary_ask_min is not None:
                if profile.salary_floor > profile.salary_ask_min:
                    raise ValueError("salary_floor must be <= salary_ask_min")
            if profile.salary_ask_min is not None and profile.salary_ask_max is not None:
                if profile.salary_ask_min > profile.salary_ask_max:
                    raise ValueError("salary_ask_min must be <= salary_ask_max")
        return v


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


class CompanyFindingModel(_Camel):
    """Wire shape for one company research finding (response)."""

    id: str = ""
    company: str = ""
    claim: str = ""
    value: str = ""
    source_url: str = ""
    source_class: str = ""
    as_of: str = ""
    observed_at: str = ""
    recorded_by: str = ""
    note: str = ""
    contradicts: list[str] = Field(default_factory=list)
    resolution: str = ""
    resolved_at: str = ""
    resolution_note: str = ""


class CompanyFindingCreate(_Camel):
    """Client-supplied fields for a new, operator-recorded company finding."""

    company: str = ""
    claim: str = ""
    value: str = ""
    source_url: str = ""
    source_class: str = ""
    as_of: str = ""
    note: str = ""

    @field_validator("source_class")
    @classmethod
    def _validate_source_class(cls, v: str) -> str:
        from companyresearch.model import SOURCE_CLASSES

        if v not in SOURCE_CLASSES:
            raise ValueError(
                f"source_class must be one of: {', '.join(SOURCE_CLASSES)}"
            )
        return v

    @field_validator("source_url")
    @classmethod
    def _validate_source_url(cls, v: str) -> str:
        if not v or "://" not in v:
            raise ValueError("source_url is required — operator writes are never uncited")
        return v


class CompanyFindingResolve(_Camel):
    """Body for resolving (accepting/rejecting) an existing finding."""

    resolution: str = ""
    note: str = ""

    @field_validator("resolution")
    @classmethod
    def _validate_resolution(cls, v: str) -> str:
        if v not in ("", "accepted", "rejected"):
            raise ValueError("resolution must be one of: '', 'accepted', 'rejected'")
        return v


class ContradictionGroupModel(_Camel):
    """One claim with two or more disagreeing, cited findings."""

    claim: str = ""
    findings: list[CompanyFindingModel] = Field(default_factory=list)


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
    posting_text: str = ""
    posted_date: str = ""
    approval: str = ""
    apply_attempts: int = 0
    apply_error: str = ""
    created_at: str = ""
    updated_at: str = ""


class ApprovalUpdate(_Camel):
    """PATCH /screenings/{id}: the operator's approval decision and/or the
    posting URL.

    ``url`` is patchable here because an imported screening can carry no URL
    (a prose migration had none to capture), and the agent cannot apply to a
    posting it has nothing to open.

    ``posting_text`` is patchable because records created before the agent
    captured it carry none, and the operator cannot draft a cover letter
    without it.

    ``role`` is patchable because a screening recorded with a garbled or
    blank title is otherwise only deletable, not correctable. The operator's
    correction is validated by ``screening.role.validate_role_title`` — the
    same rule the agent's own ``record_screening`` writes are held to.
    """

    approval: str | None = None
    url: str | None = None
    posting_text: str | None = None
    role: str | None = None

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_posting_url(v)

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_role_title(v)


class CoverLetterDraftModel(_Camel):
    """A screening's current cover letter draft.

    `source` says whether the guardrail vouches for this text: "generated" is
    exactly what generate_cover_letter produced and validated, "operator" is
    text a human wrote, which is saved verbatim and never validated.
    """

    text: str = ""
    paragraphs: list[dict] = Field(default_factory=list)
    source: str = "generated"
    updated_at: str = ""


class LetterGenerateRequest(_Camel):
    """POST /screenings/{id}/letter: draft from the stored posting text.

    `force` is the operator's explicit "discard my edits and redraft"; without
    it, regenerating over text a human wrote is refused.
    """

    force: bool = False
    tone: str = "Professional"
    length: str = "Standard"


class LetterSaveRequest(_Camel):
    """PUT /screenings/{id}/letter: the operator's own text, saved verbatim."""

    text: str


class BulkApprovalUpdate(_Camel):
    """PATCH /screenings/approvals: one decision across many screenings."""

    ids: list[str] = []
    approval: str


class BulkApprovalResult(_Camel):
    """Per-id outcome, so a partial failure is visible rather than silent."""

    results: list[dict] = []


class BulkDeleteRequest(_Camel):
    """POST /screenings/deletions: delete many screening records at once."""

    ids: list[str] = []


class BulkDeleteResult(_Camel):
    """POST /screenings/deletions response: per-id delete outcome."""

    results: list[dict] = []


class ScreeningCreate(_Camel):
    """Client-supplied fields for a new screening record.

    A resolvable posting URL is required: ``url`` is validated on creation, so
    a screening cannot be created without one.
    """

    company: str = ""
    role: str = ""
    # validate_default=True so an entirely omitted `url` key is rejected the
    # same as an explicit empty string — the validator below must run either way.
    url: str = Field(default="", validate_default=True)
    screened_date: str = ""
    verdict: str = ""
    failing_criterion: str = ""
    reason: str = ""
    cooldown_expires: str = ""
    source: str = ""
    posting_text: str = ""
    posted_date: str = ""

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        return validate_posting_url(v)

    @field_validator("role")
    @classmethod
    def _normalize_role(cls, v: str) -> str:
        return normalize_role_title(v)


class CooldownResult(_Camel):
    """Whether a company (optionally role) is currently in cooldown.

    ``window`` names which cooldown window produced the block ('same_role' or
    'same_company'); None when not in cooldown or blocked via the blocklist.
    """

    in_cooldown: bool
    expires: str | None = None
    blocked: bool = False
    window: str | None = None


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


class RouteModel(_Camel):
    """A single connection + model pair, with an optional effort level."""

    connection: str
    model: str = ""
    effort: str = ""


class RoutingModel(_Camel):
    """GET /api/routing response: all routing assignments."""

    tasks: dict[str, RouteModel] = Field(default_factory=dict)
    agent: RouteModel | None = None
    default: RouteModel | None = None


class AgentLlmCredentials(_Camel):
    """GET /api/agent/llm-credentials response: never logged, response-only egress."""

    auth_type: str
    token: str
    model: str = ""
    # Set only for Anthropic-compatible third parties (OpenRouter). Empty means
    # the agent talks to Anthropic directly, as it always did.
    base_url: str = ""


class AgentStatus(_Camel):
    """GET /api/agent/status — forwarded from the supervisor.js control server."""

    running: bool
    # True between a cancel request and the run's exit. The operator's Cancel
    # button needs to distinguish "stopping" from "running", or a run that is
    # slow to tear down reads as a cancel that did nothing.
    cancelling: bool = False
    last_started_at: str | None = None
    last_finished_at: str | None = None
    last_exit_code: int | None = None
    # Whether the last run ended because it was cancelled rather than on its
    # own. Its non-zero exit code is expected in that case, so the UI must not
    # report it as a failure.
    last_cancelled: bool = False


class AgentRunResult(_Camel):
    """POST /api/agent/run — forwarded from the supervisor.js control server."""

    started: bool
    running: bool


class AgentCancelResult(_Camel):
    """POST /api/agent/cancel — forwarded from the supervisor.js control server.

    ``cancelled`` is False when there was nothing to cancel, or when a cancel
    was already under way; it is not an error, and ``running`` reports what the
    supervisor still had in progress at the moment it answered.
    """

    cancelled: bool
    running: bool


class RoutingUpdate(_Camel):
    """Partial PUT /api/routing body — every field optional.

    Mirrors the merge semantics: omitted fields stay None and are excluded
    via `model_dump(exclude_unset=True)`, so the route only applies the
    fields the client actually sent. Unlike other merge-PUT bodies in this
    file, a field sent explicitly as `null` is NOT the same as omitting it:
    `default`/`agent` sent as null clears that route, and a task entry sent
    as null removes that task's route — see put_routing in routes.py.
    """

    tasks: dict[str, RouteModel | None] | None = None
    agent: RouteModel | None = None
    default: RouteModel | None = None
