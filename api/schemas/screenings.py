"""Wire models for the screenings queue and its cover-letter drafts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from identity.company import validate_company_name
from screening.model import validate_verdict
from screening.posting import validate_posting_text
from screening.role import normalize_role_title, validate_role_title
from identity.url import validate_posting_url

from .common import _Camel
from .cv import CoverLetterApprovals


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
    profile: str = ""
    remote_arrangement: str = ""
    language_requirement: str = ""
    approval: str = ""
    apply_attempts: int = 0
    apply_error: str = ""
    screening_blocker: str = ""
    # Lease state granted by get_approved_applications' hand-out, not by the
    # agent patching a record — never in Screening.EDITABLE. claim_expires_at
    # empty or in the past means the item is unclaimed / reclaimable.
    claimed_by_run: str = ""
    claim_expires_at: str = ""
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
    from it.

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

    `approvals` carries generation-scoped decisions on claims a previous
    attempt blocked (mirrors CoverLetterApprovals on /api/cover-letter):
    approved claims are allowed for this one generation only and are never
    written to truth.yaml. `paragraphs` echoes back the paragraphs from a
    blocked attempt so the retry re-validates that SAME letter instead of
    paying for a second LLM call; omitted, a fresh letter is generated.

    The writing style is chosen by `preset_id`; omitting it applies the user's
    default writing-style preset.
    """

    force: bool = False
    length: str = "Standard"
    approvals: CoverLetterApprovals | None = None
    paragraphs: list[dict] | None = None
    preset_id: str | None = None


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

    # validate_default=True so an entirely omitted `company` key is rejected
    # the same as an explicit empty string.
    company: str = Field(default="", validate_default=True)
    role: str = ""
    # validate_default=True so an entirely omitted `url` key is rejected the
    # same as an explicit empty string — the validator below must run either way.
    url: str = Field(default="", validate_default=True)
    screened_date: str = ""
    # validate_default=True so an entirely omitted `verdict` key is rejected
    # the same as an explicit empty string, matching record_screening's
    # requirement that a verdict is mandatory (there is no blocker on this
    # route to exempt it).
    verdict: str = Field(default="", validate_default=True)
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

    @field_validator("company")
    @classmethod
    def _validate_company(cls, v: str) -> str:
        return validate_company_name(v)

    @field_validator("verdict")
    @classmethod
    def _validate_verdict(cls, v: str) -> str:
        # Route-side blocker is never supplied here (screening_blocker is not
        # part of this schema — see the plan's out-of-scope note), so a
        # verdict is always required, matching the MCP tool's non-blocker path.
        return validate_verdict(v, blocker="")

    @model_validator(mode="after")
    def _validate_posting_text_when_queueing(self) -> "ScreeningCreate":
        # Only a validated "passed"/"deferred" verdict is about to queue for
        # the operator's decision; a "rejected" verdict is exempt, matching
        # record_screening's semantics (there is no blocker on this route).
        if self.verdict in ("passed", "deferred"):
            self.posting_text = validate_posting_text(self.posting_text)
        return self


class CooldownResult(_Camel):
    """Whether a company (optionally role) is currently in cooldown.

    ``window`` names which cooldown window produced the block ('same_role' or
    'same_company'); None when not in cooldown or blocked via the blocklist.
    """

    in_cooldown: bool
    expires: str | None = None
    blocked: bool = False
    window: str | None = None


class RejectedScreeningModel(ScreeningModel):
    """A rejected screening plus who rejected it: 'agent' or 'operator'."""

    rejected_by: Literal["agent", "operator"]


class CategoryCountModel(_Camel):
    """One rejection category and how many rejected screenings it holds."""

    key: str
    count: int


class RejectedScreeningsResponse(_Camel):
    """GET /api/screenings/rejected: one page of rejected screenings.

    ``total`` counts rows after the category filter; ``categories`` counts the
    whole rejected population before it, so the filter chips stay complete.
    ``limit``/``offset`` are the effective values after clamping.
    """

    items: list[RejectedScreeningModel]
    total: int = 0
    limit: int = 0
    offset: int = 0
    categories: list[CategoryCountModel]
