"""Wire models for tailoring, CV rendering and cover-letter generation."""

from __future__ import annotations

from pydantic import Field

from .common import _Camel


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


class CoverLetterApprovals(_Camel):
    """Generation-scoped decisions on blocked cover-letter claims. Approved
    claims are allowed for that one generation only; never persisted to
    truth.yaml (mirrors RenderApprovals)."""

    approved_claim_ids: list[str] = Field(default_factory=list)
    denied_claim_ids: list[str] = Field(default_factory=list)


class CoverLetterRequest(_Camel):
    """Request to generate a cover letter.

    The writing style is chosen by ``preset_id``; omitting it applies the
    user's default writing-style preset.
    """

    length: str = "Standard"
    # When present, the letter is saved as this application's owned document.
    application_id: str | None = None
    # Decisions on claims a previous attempt blocked, so the user can approve
    # and continue (or decline) instead of dead-ending.
    approvals: CoverLetterApprovals | None = None
    # The posting this letter is about, supplied by the caller. When omitted,
    # data/posting.txt (the last posting written by /api/tailor) is used as a
    # fallback for callers that do not send one.
    posting: str | None = None
    preset_id: str | None = None


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
    # Advisory AI-writing tells in the letter text; warn only, never block.
    style_warnings: list[AtsWarning] = Field(default_factory=list)
