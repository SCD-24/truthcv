"""CV routes: tailoring, rendering and cover-letter generation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from truthcv.integrations.providers import ProviderError, get_provider
import truthcv.services.tailor as tailor_service
from truthcv.services.render_cv import (
    DraftMissing,
    _require_application,
    render_cv,
)
from truthcv.services.cover_letter import generate_cover_letter

from .schemas import (
    AtsWarning,
    BlockedClaimModel,
    CoverLetterRequest,
    CoverLetterResult,
    RenderRequest,
    RenderResult,
    TailorRequest,
    TailorResult,
)

router = APIRouter()


@router.post("/tailor", response_model=TailorResult)
def tailor_route(body: TailorRequest) -> TailorResult:
    result = tailor_service.tailor_posting(body.posting, get_provider)
    return TailorResult.model_validate(result)


@router.post("/render", response_model=RenderResult)
def render_route(body: RenderRequest | None = None) -> RenderResult:
    # Thin marshalling: pull the request-derived arguments, run the framework-
    # free render workflow, and translate its outcome (or its DraftMissing) into
    # the HTTP response. All business logic — the guardrail, scope-building and
    # approval-filtering — lives in services/render_cv.py.
    app_id = body.application_id if body else None
    approved: set[str] = set()
    denied: set[str] = set()
    if body and body.approvals:
        approved = set(body.approvals.approved_claim_ids)
        denied = set(body.approvals.denied_claim_ids)

    try:
        outcome = render_cv(application_id=app_id, approved=approved, denied=denied)
    except DraftMissing:
        raise HTTPException(
            status_code=400, detail="Tailor a posting before rendering."
        ) from None

    if outcome.blocked:
        blocked = [
            BlockedClaimModel(
                claim_id=c.claim_id,
                experience_id=c.experience_id,
                text=c.text,
                tokens=c.tokens,
            )
            for c in outcome.blocked_claims
        ]
        return RenderResult(
            blocked=True, unverifiable=outcome.unverifiable, blocked_claims=blocked
        )

    # A pure wizard preview (no application) has no saved document to fall back
    # on, so an unavailable backend is still a hard error there. An attached
    # render keeps its saved link even when nothing could be produced.
    if outcome.pdf_url is None and outcome.docx_url is None and not app_id:
        raise HTTPException(
            status_code=500,
            detail="Rendering backend unavailable (WeasyPrint/pandoc not installed).",
        )

    return RenderResult(
        blocked=False,
        ats_warnings=[AtsWarning(**w) for w in outcome.ats_warnings],
        pdf_url=outcome.pdf_url,
        docx_url=outcome.docx_url,
        html=outcome.html,
        render_unavailable=outcome.render_unavailable,
    )


@router.post("/cover-letter", response_model=CoverLetterResult)
def cover_letter(body: CoverLetterRequest) -> CoverLetterResult:
    # Thin marshalling: validate the id (404 on miss), run the framework-free
    # cover-letter workflow, and translate its outcome — or its DraftMissing, or
    # an LLM failure — into the HTTP response. All business logic (posting
    # resolution, render-scoped approvals, the guardrail and best-effort render)
    # lives in services/cover_letter.py.
    _require_application(body.application_id)

    approved_ids = set(body.approvals.approved_claim_ids) if body.approvals else set()
    denied_ids = set(body.approvals.denied_claim_ids) if body.approvals else set()
    app_id = body.application_id if body.application_id else None

    try:
        outcome = generate_cover_letter(
            application_id=app_id,
            posting=body.posting,
            preset_id=body.preset_id,
            length=body.length,
            provider=get_provider("cover_letter"),
            approved_ids=approved_ids,
            denied_ids=denied_ids,
        )
    except DraftMissing:
        raise HTTPException(
            status_code=400, detail="Tailor a posting before generating a cover letter."
        ) from None
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"The language model call failed: {type(e).__name__}: {e}",
        ) from e

    if outcome.blocked:
        blocked_claims = [
            BlockedClaimModel(
                claim_id=c.claim_id,
                experience_id=c.experience_id,
                text=c.text,
                tokens=c.tokens,
            )
            for c in outcome.blocked_claims
        ]
        return CoverLetterResult(
            blocked=True,
            unverifiable=outcome.unverifiable,
            blocked_claims=blocked_claims,
        )

    # Only a pure preview (no application) hard-errors on an unavailable backend;
    # an attached save keeps its recorded link.
    if outcome.pdf_url is None and outcome.docx_url is None and not app_id:
        raise HTTPException(
            status_code=500,
            detail="Rendering backend unavailable (WeasyPrint/pandoc not installed).",
        )
    return CoverLetterResult(
        blocked=False,
        pdf_url=outcome.pdf_url,
        docx_url=outcome.docx_url,
        text=outcome.text,
        render_unavailable=outcome.render_unavailable,
        style_warnings=[AtsWarning(**w) for w in outcome.style_warnings],
    )
