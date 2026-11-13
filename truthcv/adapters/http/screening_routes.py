"""Screening routes: the screening queue, its approvals, letters and the cooldown check."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from truthcv.integrations.providers import get_provider
import truthcv.services.screenings as screenings_service
import truthcv.services.screening_letters as screening_letters_service
from truthcv.domain.screening import store as screening_store
from truthcv.domain.screening.cooldown import cooldown as check_cooldown
from truthcv.domain.screening.model import Screening

import truthcv.engines.coverletter.store as letter_store

from .route_support import _application_model
from .schemas import (
    ApplicationModel,
    ApprovalUpdate,
    BulkApprovalResult,
    BulkApprovalUpdate,
    BulkDeleteRequest,
    BulkDeleteResult,
    CategoryCountModel,
    CooldownResult,
    CoverLetterDraftModel,
    LetterGenerateRequest,
    LetterSaveRequest,
    RejectedScreeningModel,
    RejectedScreeningsResponse,
    ScreeningCreate,
    ScreeningModel,
)

router = APIRouter()


def _screening_model(screening: Screening) -> ScreeningModel:
    """Map a stored Screening to its wire model.

    The approval fields sit outside EDITABLE — so the agent cannot set them —
    and are therefore mapped explicitly rather than picked up by the loop.
    """
    data = {f: getattr(screening, f) for f in Screening.EDITABLE}
    return ScreeningModel(
        id=screening.id,
        created_at=screening.created_at,
        updated_at=screening.updated_at,
        approval=screening.approval,
        apply_attempts=screening.apply_attempts,
        apply_error=screening.apply_error,
        claimed_by_run=screening.claimed_by_run,
        claim_expires_at=screening.claim_expires_at,
        **data,
    )


@router.get("/screenings", response_model=list[ScreeningModel])
def list_screenings(approval: str | None = None) -> list[ScreeningModel]:
    """Every screening record, most recent first; `approval` narrows to the queue."""
    return [_screening_model(s) for s in screenings_service.list_screenings(approval)]


# Default page size for GET /screenings/rejected; the store clamps the bounds.
REJECTED_DEFAULT_LIMIT = 50


def _rejected_model(row: screening_store.RejectedRow) -> RejectedScreeningModel:
    """Wire model for one rejected row: the screening plus who rejected it."""
    return RejectedScreeningModel(
        **_screening_model(row.screening).model_dump(), rejected_by=row.rejected_by
    )


@router.get("/screenings/rejected", response_model=RejectedScreeningsResponse)
def list_rejected_screenings(
    limit: int = REJECTED_DEFAULT_LIMIT,
    offset: int = 0,
    category: str = screening_store.REJECTED_ALL,
) -> RejectedScreeningsResponse:
    """One page of rejected screenings, newest first, with category counts.

    Declared before the `/screenings/{screening_id}` routes so `rejected` is
    never read as an id. limit is clamped into the store's bounds and a
    negative offset to 0; the effective values are echoed back.
    """
    page = screenings_service.rejected_page(limit, offset, category)
    return RejectedScreeningsResponse(
        items=[_rejected_model(r) for r in page.rows],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        categories=[CategoryCountModel(key=k, count=c) for k, c in page.counts],
    )


@router.post("/screenings", response_model=ScreeningModel, status_code=201)
def create_screening(body: ScreeningCreate) -> ScreeningModel:
    """Create a new screening record from client-supplied fields.

    A screening cannot be created without a resolvable posting URL: the
    requirement is enforced by ``ScreeningCreate``'s ``url`` validator, which
    surfaces an unusable URL as a 422 before this handler runs.

    409 when the store already holds a screening for that posting: one
    posting gets one record, so a second is refused rather than silently
    merged into the first, and the existing record's id is returned in the
    detail so the caller can go and look at it. Delete that record to screen
    the posting again.

    A passed/deferred verdict for a blocklisted company is stored as
    rejected, never queued; the service owns that rule.
    """
    screening, created = screenings_service.create_screening(
        body.model_dump(by_alias=False)
    )
    if not created:
        raise HTTPException(
            status_code=409,
            detail=(
                "This posting has already been screened "
                f"(screening {screening.id})."
            ),
        )
    return _screening_model(screening)


# Declared BEFORE /screenings/{screening_id}: otherwise the router binds
# "approvals" as an id and this route is unreachable.
@router.patch("/screenings/approvals", response_model=BulkApprovalResult)
def bulk_set_approval(body: BulkApprovalUpdate) -> BulkApprovalResult:
    """Apply one approval decision to many screenings.

    Reports per-id outcomes rather than failing wholesale, so a partial failure
    is visible instead of silently dropping some ids. A draftless id is approved
    the same way as any other — the agent applies with whatever cover letter is
    stored, or none.
    """
    results = screenings_service.bulk_set_approval(body.ids, body.approval)
    return BulkApprovalResult(results=results)


@router.post("/screenings/{screening_id}/applied", response_model=ApplicationModel, status_code=201)
def mark_screening_applied(screening_id: str) -> ApplicationModel:
    """Record that the operator applied to this posting by hand.

    Creates the Applications row from what the screening already knows and
    retires the queue item, so a manual application is tracked the same way an
    agent-submitted one is. `submitted` is true and `capture_method` says the
    operator did it, which is the only thing distinguishing the two afterwards.

    409 rather than a second row when the screening has already been applied:
    a double click must not create a duplicate application.
    """
    return _application_model(screenings_service.mark_applied(screening_id))


# Declared BEFORE /screenings/{screening_id}: otherwise the router binds
# "deletions" as an id and this route is unreachable.
@router.post("/screenings/deletions", response_model=BulkDeleteResult)
def bulk_delete_screenings(body: BulkDeleteRequest) -> BulkDeleteResult:
    """Delete many screening records at once.

    Reports per-id outcomes rather than failing wholesale, so a partial
    failure is visible instead of silently dropping some ids. An unknown id
    is reported ok:false, never a 404 — an empty list is a no-op.
    """
    results = [
        {"id": sid, "ok": ok} for sid, ok in screenings_service.delete_screenings(body.ids)
    ]
    return BulkDeleteResult(results=results)


@router.patch("/screenings/{screening_id}", response_model=ScreeningModel)
def set_screening_approval(screening_id: str, body: ApprovalUpdate) -> ScreeningModel:
    """The operator's approval decision and/or posting URL for one screening."""
    if (
        body.approval is None
        and body.url is None
        and body.posting_text is None
        and body.role is None
    ):
        raise HTTPException(
            status_code=422, detail="Provide approval, role, url or postingText."
        )

    screening = screenings_service.update_screening(
        screening_id,
        role=body.role,
        url=body.url,
        posting_text=body.posting_text,
        approval=body.approval,
    )
    return _screening_model(screening)


def _draft_model(draft: letter_store.CoverLetterDraft) -> CoverLetterDraftModel:
    return CoverLetterDraftModel.model_validate(draft.to_dict())


@router.get("/screenings/{screening_id}/letter", response_model=CoverLetterDraftModel)
def get_screening_letter(screening_id: str) -> CoverLetterDraftModel:
    """The screening's current draft."""
    draft = letter_store.load(screening_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No cover letter drafted yet.")
    return _draft_model(draft)


@router.post("/screenings/{screening_id}/letter", response_model=CoverLetterDraftModel)
def generate_screening_letter(
    screening_id: str, body: LetterGenerateRequest
) -> CoverLetterDraftModel:
    """Draft the letter for one screening, on the operator's request.

    Guardrailed exactly as the agent's own generation is — this is the same
    function the agent calls. A blocked generation writes nothing and reports
    the claims that blocked it, so the operator can fix the truth document
    rather than discovering the block at approval time.

    The retry can carry `approvals` and the blocked attempt's `paragraphs` to
    re-validate the SAME letter, mirroring `/api/cover-letter`.
    """
    approvals = body.approvals
    draft = screening_letters_service.generate(
        screening_id,
        force=body.force,
        approved_ids=approvals.approved_claim_ids if approvals else None,
        denied_ids=approvals.denied_claim_ids if approvals else None,
        paragraphs=body.paragraphs,
        preset_id=body.preset_id,
        length=body.length,
        provider_factory=get_provider,
    )
    return _draft_model(draft)


@router.put("/screenings/{screening_id}/letter", response_model=CoverLetterDraftModel)
def save_screening_letter(
    screening_id: str, body: LetterSaveRequest
) -> CoverLetterDraftModel:
    """Save the operator's own text, verbatim and unvalidated.

    The one path in the system where text reaches an employer without passing
    guardrail/validate.py, and deliberately so: the guardrail exists to stop the
    AGENT asserting facts it cannot ground in the operator's truth document. The
    operator is the source of that document. `source` records that a human wrote
    this, and the agent applies with it unchanged.
    """
    return _draft_model(screening_letters_service.save_operator_text(screening_id, body.text))


@router.delete("/screenings/{screening_id}", status_code=204)
def delete_screening(screening_id: str) -> None:
    """Delete a screening record."""
    if not screenings_service.delete_screening(screening_id):
        raise HTTPException(status_code=404, detail="Screening not found.")


@router.get("/cooldown", response_model=CooldownResult)
def get_cooldown(company: str, role: str | None = None) -> CooldownResult:
    """Whether `company` (optionally narrowed by `role`) is currently in cooldown.

    Delegates entirely to screening.cooldown.cooldown; no arithmetic here.
    """
    status = check_cooldown(company, role)
    return CooldownResult(
        in_cooldown=status.in_cooldown,
        expires=status.expires,
        blocked=status.blocked,
        window=getattr(status, "window", None),
    )
