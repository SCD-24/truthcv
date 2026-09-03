"""Wizard REST routes wired to the backend modules.

The one hard rule lives in /api/render: the guardrail runs BEFORE any file is
produced, and if it fails nothing is rendered — the response is blocked=true with
the unverifiable tokens.
"""

from __future__ import annotations

import hmac
import json
import os
from datetime import date
import urllib.error
import urllib.request
from urllib.parse import urlparse

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

import tailor as tailor_engine
from providers import ProviderError, get_provider
from render import render_docx, render_pdf
from render.pdf import RenderUnavailable
from truth import load, persist_source_hash, save
from truth.answers import Answers
from truth.answers import load as load_answers
from truth.answers import save as save_answers
from truth.document import extract_document_text, extension_for
from truth.extract import build_truth_from_text
from services.inferences import confirm_inferences as confirm_inferences_service
import services.screenings as screenings_service
import services.agent_config as agent_config_service
import services.applications as applications_service
from truth.model import Truth
from truth.pdf import (
    DocumentExtractError,
    has_profile,
    load_source_text,
    persist_profile,
    persist_source_text,
)

import applications as app_store
import modelrouting
import secretstore
from services.render_cv import (
    DraftMissing,
    _claim_id,
    _contact_line,
    _require_application,
    render_cv,
)
from services.cover_letter import generate_cover_letter
from onboarding import store as onboarding_store
from agentconfig import store as agent_config_store
from connections import catalog
from connections.auth.claude import AuthError, get_valid_access_token
from connections.auth import claude as claude_auth
from connections.auth import codex as codex_auth
from providers import (
    ANTHROPIC_COMPAT_OPENROUTER_BASE_URL,
    OPENROUTER_BASE_URL,
    build_connection_provider,
    reset_provider,
)
from providers.base import supports_effort_levels
from companyresearch import store as company_findings_store
from screening import store as screening_store
from runs import store as runs_store
from runs.derive import counters_by_run
from screening.company import company_identity_key
from screening.cooldown import cooldown as check_cooldown
from screening.model import Screening

import coverletter.store as letter_store
from agenttools.letter_operator import generate_cover_letter_for_operator as _generate_letter_for_operator

from .schemas import (
    AgentConfigModel,
    ApprovalUpdate,
    BulkApprovalResult,
    BulkApprovalUpdate,
    BulkDeleteRequest,
    BulkDeleteResult,
    CoverLetterDraftModel,
    LetterGenerateRequest,
    LetterSaveRequest,
    AgentCancelResult,
    AgentConfigUpdate,
    AgentLlmCredentials,
    AgentRunAccountingResult,
    AgentRunFinish,
    AgentRunResult,
    AgentRunStart,
    AgentStatus,
    AnswersModel,
    AnswersUpdate,
    ApiKeyRequest,
    ApplicationCreate,
    ApplicationDocument,
    ApplicationListResponse,
    ApplicationModel,
    ApplicationUpdate,
    AtsWarning,
    CompleteLoginRequest,
    ConfirmInferencesRequest,
    ConnectionList,
    ConnectionStatus,
    ConnectionTestRequest,
    CompanyFindingCreate,
    CompanyFindingModel,
    CompanyFindingResolve,
    ContradictionGroupModel,
    CoverLetterApprovals,
    CoverLetterRequest,
    CooldownResult,
    CoverLetterResult,
    JobBoardKeyStatus,
    JobBoardKeyUpdate,
    ModelInfo,
    ModelList,
    BlockedClaimModel,
    OnboardingState,
    OnboardingUpdate,
    ProfileStatus,
    RenderRequest,
    RenderResult,
    RouteModel,
    RunListResponse,
    RunModel,
    RoutingModel,
    RoutingUpdate,
    SaveCoverLetterRequest,
    SaveCvRequest,
    SaveDocumentResult,
    ScreeningCreate,
    ScreeningModel,
    SettingsStatus,
    SettingsUpdate,
    SigninQueue,
    SigninQueueSite,
    BrowserSession,
    BrowserSessionClosed,
    BrowserSessionRequest,
    PollLoginResult,
    StartLoginResult,
    TailorRequest,
    TailorResult,
    TestResult,
    TruthDoc,
)

router = APIRouter(prefix="/api")


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
    screenings = sorted(
        screening_store.load_all(), key=lambda s: s.created_at, reverse=True
    )
    if approval is not None:
        screenings = [s for s in screenings if s.approval == approval]
    return [_screening_model(s) for s in screenings]


def _run_models(records: list) -> list[RunModel]:
    """Wire models for run records, with their coverage counters DERIVED.

    screenings_recorded, blocked_count, queued_for_approval and
    applications_submitted are recomputed from the records each run actually
    produced and OVERRIDE whatever is stored on the run record; postings_seen,
    over_cap_writes, stopped_reason, note, status and the timestamps are read
    from the stored record unchanged. Both run routes go through here so the
    two surfaces cannot disagree — the same reasoning check_cooldown gives for
    sharing one function.

    Each store is loaded ONCE for the whole list, not once per run. A run still
    "running" derives live counts, which is intended: the numbers describe the
    records that exist right now.

    Derivation is best-effort, in the spirit of the rest of this subsystem: if
    a store cannot be loaded, the stored values are served rather than failing
    the request. Only the load is guarded, not the response build.
    """
    try:
        screenings = screening_store.load_all()
        applications = app_store.load_all()
    except Exception:
        return [RunModel(**r.to_dict()) for r in records]
    counters = counters_by_run([r.id for r in records], screenings, applications)
    return [RunModel(**{**r.to_dict(), **counters.get(r.id, {})}) for r in records]


@router.get("/runs", response_model=RunListResponse)
def list_runs(limit: int = 50, offset: int = 0) -> RunListResponse:
    """One page of the most recently started agent runs, newest first.

    Reads the shared data volume in-process via runs.store — this does NOT
    proxy to the supervisor, unlike the /agent/* routes, because the run
    records live on the volume the API already has access to.

    A negative offset is clamped to 0 rather than rejected: it is a client
    that paged past the start, and an empty first page is a worse answer than
    the first page. An offset past the end yields an empty page — the total
    tells the client it overshot.

    The page and its total come from one read of the store, so they always
    describe the same set of runs; a run recorded between two reads would
    otherwise be reported as an older run that had gone missing.
    """
    offset = max(0, offset)
    records, total = runs_store.list_page(limit=limit, offset=offset)
    return RunListResponse(
        runs=_run_models(records),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=RunModel)
def get_run(run_id: str) -> RunModel:
    """A single run record, or 404 if no run with this id has been recorded."""
    record = runs_store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_models([record])[0]


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
    try:
        results = []
        for sid in body.ids:
            results.append(
                {"id": sid, "ok": screening_store.set_approval(sid, body.approval) is not None}
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
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
    if screening_store.get(screening_id) is None:
        raise HTTPException(status_code=404, detail="Screening not found.")

    # Retire FIRST, atomically, and create the row only if this call is the one
    # that won the claim. Checking then creating then retiring let two requests
    # both pass the check and create two Applications rows for one posting —
    # two tabs, or one slow response and a second click, was enough. Ordering
    # it this way also means a crash between the two writes leaves a retired
    # screening with no row (visible, fixable) rather than a duplicate row.
    result = screenings_service.claim_screening_for_apply(screening_id)
    if result.refused:
        if result.reason == "contradictory_research":
            refused = result.refused_screening
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{refused.company} has an open company-research contradiction — "
                    "resolve it at /api/company-findings/contradictions before applying."
                ),
            )
        raise HTTPException(
            status_code=409, detail="This screening has already been applied to."
        )
    screening = result.screening

    app = app_store.create(
        {
            "company": screening.company,
            "role": screening.role,
            "application_url": screening.url,
            "posting": screening.posting_text,
            "submission_type": "Posting" if screening.url else "General",
            "submitted": True,
            "status": "Applied",
            "application_date": date.today().isoformat(),
            "capture_method": "manual",
            "screening_id": screening_id,
        }
    )
    return _application_model(app)


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
        {"id": sid, "ok": ok} for sid, ok in screening_store.delete_many(body.ids)
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

    screening = None
    if body.role is not None:
        screening = screening_store.update(screening_id, {"role": body.role})
        if screening is None:
            raise HTTPException(status_code=404, detail="Screening not found.")

    if body.url is not None:
        screening = screening_store.update(screening_id, {"url": body.url})
        if screening is None:
            raise HTTPException(status_code=404, detail="Screening not found.")

    if body.posting_text is not None:
        screening = screening_store.update(
            screening_id, {"posting_text": body.posting_text}
        )
        if screening is None:
            raise HTTPException(status_code=404, detail="Screening not found.")

    if body.approval is not None:
        # Existence wins over the unknown-id check: an unknown id is 404
        # regardless of approval value, matching the url-only branch above.
        try:
            screening = screening_store.set_approval(screening_id, body.approval)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        if screening is None:
            raise HTTPException(status_code=404, detail="Screening not found.")

    return _screening_model(screening)


def _company_finding_model(f) -> CompanyFindingModel:
    """Map a stored CompanyFinding to its wire model."""
    return CompanyFindingModel(**f.to_dict())


@router.get("/company-findings", response_model=list[CompanyFindingModel])
def list_company_findings() -> list[CompanyFindingModel]:
    """Every company research finding, newest observed_at first."""
    findings = sorted(
        company_findings_store.load_all(), key=lambda f: f.observed_at, reverse=True
    )
    return [_company_finding_model(f) for f in findings]


# Declared BEFORE /company-findings/{company}: otherwise the router binds
# "contradictions" as a company name and this route is unreachable.
@router.get(
    "/company-findings/contradictions", response_model=list[ContradictionGroupModel]
)
def list_company_finding_contradictions(
    company: str | None = None,
) -> list[ContradictionGroupModel]:
    """Open contradiction groups; narrowed to one company, or across all of them."""
    if company is not None:
        groups = company_findings_store.open_contradictions(company)
    else:
        companies = {f.company for f in company_findings_store.load_all()}
        groups = []
        for c in companies:
            groups.extend(company_findings_store.open_contradictions(c))
    return [
        ContradictionGroupModel(
            claim=g["claim"],
            findings=[_company_finding_model(f) for f in g["findings"]],
        )
        for g in groups
    ]


@router.get("/company-findings/{company}", response_model=list[CompanyFindingModel])
def list_company_findings_for(company: str) -> list[CompanyFindingModel]:
    """Every finding recorded for one company."""
    return [
        _company_finding_model(f) for f in company_findings_store.for_company(company)
    ]


@router.post("/company-findings", response_model=CompanyFindingModel, status_code=201)
def create_company_finding(body: CompanyFindingCreate) -> CompanyFindingModel:
    """Record an operator-sourced company finding. Never overwrites an existing one."""
    try:
        finding = company_findings_store.record(
            company=body.company,
            claim=body.claim,
            value=body.value,
            source_url=body.source_url,
            source_class=body.source_class,
            as_of=body.as_of,
            recorded_by="operator",
            note=body.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _company_finding_model(finding)


@router.patch("/company-findings/{finding_id}", response_model=CompanyFindingModel)
def resolve_company_finding(
    finding_id: str, body: CompanyFindingResolve
) -> CompanyFindingModel:
    """Accept or reject an existing finding. Cannot change its factual fields."""
    try:
        finding = company_findings_store.resolve(
            finding_id, body.resolution, body.note
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found.")
    return _company_finding_model(finding)


def _draft_model(draft: letter_store.CoverLetterDraft) -> CoverLetterDraftModel:
    return CoverLetterDraftModel.model_validate(draft.to_dict())


@router.get("/screenings/{screening_id}/letter", response_model=CoverLetterDraftModel)
def get_screening_letter(screening_id: str) -> CoverLetterDraftModel:
    """The screening's current draft."""
    draft = letter_store.load(screening_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No cover letter drafted yet.")
    return _draft_model(draft)


def _screening_letter_approvals(
    approvals: CoverLetterApprovals | None,
    paragraphs: list[dict] | None,
) -> tuple[set[str], set[str]]:
    """Resolve blocked-claim ids to claim texts against the paragraphs SUPPLIED
    IN THIS REQUEST, not the wizard's cached draft (_letter_approvals uses that
    one; it is wrong here — a screening's letter is per-screening, not global).
    Mirrors the wizard's id derivation exactly: LETTER_SCOPE_ID + _claim_id.
    """
    if not approvals or not paragraphs:
        return set(), set()

    from coverletter import LETTER_SCOPE_ID

    approved_ids = set(approvals.approved_claim_ids)
    denied_ids = set(approvals.denied_claim_ids)
    approved: set[str] = set()
    denied: set[str] = set()
    for para in paragraphs:
        for claim in para.get("claims", []):
            cid = _claim_id(LETTER_SCOPE_ID, claim)
            if cid in approved_ids:
                approved.add(claim)
            if cid in denied_ids:
                denied.add(claim)
    return approved, denied


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
    screening = screening_store.get(screening_id)
    if screening is None:
        raise HTTPException(status_code=404, detail="Screening not found.")
    if not screening.posting_text.strip():
        raise HTTPException(
            status_code=409,
            detail="No posting text stored for this screening, so there is nothing to draft from.",
        )
    existing = letter_store.load(screening_id)
    if existing is not None and existing.source == "operator" and not body.force:
        raise HTTPException(
            status_code=409,
            detail="This letter was edited by you. Redrafting would discard those edits.",
        )
    approved_texts, denied_texts = _screening_letter_approvals(body.approvals, body.paragraphs)
    result = _generate_letter_for_operator(
        posting=screening.posting_text,
        tone=body.tone,
        length=body.length,
        approved_texts=approved_texts,
        denied_texts=denied_texts,
        paragraphs=body.paragraphs,
        company=screening.company or None,
    )
    if result["blocked"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The letter was blocked by the truthfulness guardrail.",
                "blockedReason": result.get("blocked_reason", ""),
                "blockedClaims": [
                    {
                        "claimId": _claim_id(c["scope_id"], c["text"]),
                        "experienceId": c["scope_id"],
                        "text": c["text"],
                        "tokens": c["tokens"],
                    }
                    for c in result["blocked_claims"]
                ],
                "paragraphs": result["paragraphs"],
            },
        )
    draft = letter_store.CoverLetterDraft(
        text=result["text"], paragraphs=result["paragraphs"], source="generated"
    )
    return _draft_model(letter_store.save(screening_id, draft))


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
    if screening_store.get(screening_id) is None:
        raise HTTPException(status_code=404, detail="Screening not found.")
    if not body.text.strip():
        raise HTTPException(
            status_code=422,
            detail="An empty letter cannot be saved — blanking is not an edit; regenerate instead.",
        )
    existing = letter_store.load(screening_id)
    draft = letter_store.CoverLetterDraft(
        text=body.text,
        paragraphs=existing.paragraphs if existing else [],
        source="operator",
    )
    return _draft_model(letter_store.save(screening_id, draft))


@router.delete("/screenings/{screening_id}", status_code=204)
def delete_screening(screening_id: str) -> None:
    """Delete a screening record."""
    if not screening_store.delete(screening_id):
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


def _truth_doc(truth: Truth) -> TruthDoc:
    return TruthDoc.model_validate(truth.to_dict())


MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MiB — a CV/cover-letter upload has no legitimate reason to exceed this


@router.post("/upload", status_code=204)
async def upload(file: UploadFile = File(...)) -> None:
    # Read one byte past the cap so an oversized upload is detected without
    # ever buffering the whole body into process memory.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail="Upload exceeds the maximum allowed size."
        )
    ext = extension_for(file.filename or "")
    try:
        text = extract_document_text(file.filename or "", data)
    except DocumentExtractError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    persist_source_text(text)
    persist_source_hash(text)  # keyed cache: lets /extract skip a repeat LLM pass
    persist_profile(data, ext)


@router.post("/extract", response_model=TruthDoc)
def extract() -> TruthDoc:
    text = load_source_text()
    if not text.strip():
        raise HTTPException(status_code=400, detail="Upload your CV before extracting.")
    try:
        truth = build_truth_from_text(text, get_provider("truth_extract"))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 — surface upstream LLM/SDK errors cleanly
        raise HTTPException(
            status_code=502,
            detail=f"The language model call failed: {type(e).__name__}: {e}",
        ) from e
    return _truth_doc(truth)


@router.get("/truth", response_model=TruthDoc)
def get_truth() -> TruthDoc:
    return _truth_doc(load())


@router.put("/truth", status_code=204)
def put_truth(body: TruthDoc) -> None:
    truth = Truth.from_dict(body.model_dump(by_alias=False))
    try:
        save(truth)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/tailor", response_model=TailorResult)
def tailor_route(body: TailorRequest) -> TailorResult:
    try:
        result = tailor_engine.tailor(body.posting, load(), get_provider)
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 — surface upstream LLM/SDK errors cleanly
        raise HTTPException(
            status_code=502,
            detail=f"The language model call failed: {type(e).__name__}: {e}",
        ) from e
    from storage import data_dir

    (data_dir() / "posting.txt").write_text(body.posting, encoding="utf-8")
    return TailorResult.model_validate(
        {"keywords": result["keywords"], "inferences": result["inferences"]}
    )


@router.post("/confirm-inferences", status_code=204)
def confirm_inferences(body: ConfirmInferencesRequest) -> None:
    confirm_inferences_service(body.approved, body.approved_ids)


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


def _download_url(name: str) -> str | None:
    """Download URL for a rendered file, or None if it isn't on the volume.

    Why check existence: a file may be recorded on the application but missing in
    an environment where WeasyPrint/pandoc wasn't available at save time.
    """
    if not name:
        return None
    from storage import data_dir

    return f"/api/download/{name}" if (data_dir() / name).exists() else None


def _document_model(doc) -> ApplicationDocument | None:
    """Map a stored Document to its wire model (filenames -> download URLs)."""
    if doc is None:
        return None
    return ApplicationDocument(
        source=doc.source,
        pdf_url=_download_url(doc.pdf_filename),
        docx_url=_download_url(doc.docx_filename),
        updated_at=doc.updated_at,
    )


def _application_model(app) -> ApplicationModel:
    """Map a stored Application to its wire model."""
    data = {f: getattr(app, f) for f in app.EDITABLE}
    return ApplicationModel(
        id=app.id,
        created_at=app.created_at,
        updated_at=app.updated_at,
        cv_document=_document_model(app.cv_document),
        cover_letter_document=_document_model(app.cover_letter_document),
        fields_submitted=[f.to_dict() for f in app.fields_submitted],
        confirmation=app.confirmation.to_dict(),
        screening=app.screening.to_dict(),
        attachments=[a.to_dict() for a in app.attachments],
        **data,
    )


@router.get("/applications", response_model=list[ApplicationModel])
def list_applications(q: str = "") -> list[ApplicationModel]:
    """Every tracked job application, most recent first.

    q: case-insensitive substring filter over company, website, application URL,
    notes, posting and role; empty returns everything
    """
    apps = applications_service.list_applications(q)
    return [_application_model(a) for a in apps]


@router.get("/applications/page", response_model=ApplicationListResponse)
def list_applications_page(
    limit: int = 25, offset: int = 0, sort: str = "date", direction: str = "desc", q: str = ""
) -> ApplicationListResponse:
    """One page of applications, server-sorted and paginated.

    ``q`` is the same case-insensitive substring filter as GET /api/applications
    (company, website, application URL, notes, posting, role); it is applied
    before paging so ``total`` counts matches.

    Reads the application store in-process and returns a paginated, sorted page
    of applications with the total count across all records. Sort keys and
    direction are passed through and echoed in the response.

    A negative offset is clamped to 0 rather than rejected: it is a client that
    paged past the start, and an empty first page is a worse answer than the
    first page. An offset past the end yields an empty page — the total tells
    the client it overshot.
    """
    offset = max(0, offset)
    try:
        apps, total = applications_service.list_applications_page(
            limit=limit, offset=offset, sort=sort, direction=direction, q=q
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApplicationListResponse(
        applications=[_application_model(a) for a in apps],
        total=total,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


@router.get("/applications/export")
def export_applications() -> StreamingResponse:
    """Download every application as a CSV plus per-company document folders.

    Bundled as one zip so a user gets an offline, portable record of the whole
    tracker: the table as `applications.csv`, and each application's rendered
    files grouped under a folder named for its company.
    """
    apps = applications_service.list_applications()
    archive = applications_service.build_export_zip(apps)
    headers = {"Content-Disposition": 'attachment; filename="applications.zip"'}
    return StreamingResponse(archive, media_type="application/zip", headers=headers)


@router.post("/applications", response_model=ApplicationModel, status_code=201)
def create_application(body: ApplicationCreate) -> ApplicationModel:
    """Create a new application record from client-supplied fields."""
    app = applications_service.create_application_record(body.model_dump(by_alias=False))
    return _application_model(app)


@router.put("/applications/{app_id}", response_model=ApplicationModel)
def update_application(app_id: str, body: ApplicationUpdate) -> ApplicationModel:
    """Patch an application's editable fields (None fields are left unchanged)."""
    patch = body.model_dump(by_alias=False, exclude_none=True)
    app = applications_service.update_application_record(app_id, patch)
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    return _application_model(app)


@router.delete("/applications/{app_id}", status_code=204)
def delete_application(app_id: str) -> None:
    """Delete an application and remove its owned document files."""
    if not app_store.delete(app_id):
        raise HTTPException(status_code=404, detail="Application not found.")


def _strip_html(text: str) -> str:
    """Drop tags/entities so the guardrail sees prose, not markup.

    Why: an edited CV arrives as HTML; tag names like `p`/`div` are not claims
    and must not be diffed against the truth. Cover-letter text passes through
    unchanged (it has no markup).
    """
    import html as html_lib
    import re

    without_tags = re.sub(r"<[^>]+>", " ", text or "")
    return html_lib.unescape(without_tags)


def _render_to_files(html: str, pdf_name: str, docx_name: str) -> bool:
    """Best-effort render HTML to the named PDF and DOCX on the volume.

    Returns True if at least one format was produced. It never raises on an
    unavailable backend: callers that have already recorded the document must
    keep the saved link even when WeasyPrint/pandoc are missing, and the
    download-URL builder nulls links for files that were not produced.
    """
    produced = False
    try:
        render_pdf(html, pdf_name)
        produced = True
    except RenderUnavailable:
        pass
    try:
        render_docx(html, docx_name)
        produced = True
    except RenderUnavailable:
        pass
    return produced


@router.put("/applications/{app_id}/cv", response_model=SaveDocumentResult)
def save_application_cv(app_id: str, body: SaveCvRequest) -> SaveDocumentResult:
    """Render and save edited CV HTML onto an application.

    A manual edit is a deliberate human decision, so it is trusted and saved
    as-is — the truthfulness guardrail only gates the automatic AI generation
    (/render, /tailor), not a document the user edited by hand.
    """
    if app_store.get(app_id) is None:
        raise HTTPException(status_code=404, detail="Application not found.")

    # Record the document FIRST so the link always persists, then render
    # best-effort — a missing render backend must never lose the saved CV.
    app = app_store.save_cv_document(app_id, body.html)
    pdf_name, docx_name = app_store.cv_filenames(app_id)
    produced = _render_to_files(body.html, pdf_name, docx_name)
    return SaveDocumentResult(
        blocked=False,
        application=_application_model(app),
        render_unavailable=not produced,
    )


@router.put("/applications/{app_id}/cover-letter", response_model=SaveDocumentResult)
def save_application_cover_letter(
    app_id: str, body: SaveCoverLetterRequest
) -> SaveDocumentResult:
    """Render and save edited cover-letter text on an app.

    A manual edit is trusted and saved as-is; the truthfulness guardrail only
    gates the automatic AI generation, not a hand-edited document.
    """
    if app_store.get(app_id) is None:
        raise HTTPException(status_code=404, detail="Application not found.")

    from render.cover_letter import render_letter_html

    _profile = load().profile
    html = render_letter_html(
        body.text,
        name=_profile.name or "Your Name",
        contact=_contact_line(_profile),
    )
    # Record the document FIRST so the link always persists, then render
    # best-effort — a missing backend must never lose the saved cover letter.
    app = app_store.save_cover_letter_document(app_id, body.text)
    pdf_name, docx_name = app_store.cover_letter_filenames(app_id)
    produced = _render_to_files(html, pdf_name, docx_name)
    return SaveDocumentResult(
        blocked=False,
        application=_application_model(app),
        render_unavailable=not produced,
    )


_V1_PROVIDER_TO_CARD = {"anthropic": "claude", "openai": "codex", "ollama": "ollama"}
_CARD_TO_V1_PROVIDER = {v: k for k, v in _V1_PROVIDER_TO_CARD.items()}


def _settings_status() -> SettingsStatus:
    routing = modelrouting.load()
    if routing.default is not None:
        active_provider = _CARD_TO_V1_PROVIDER.get(routing.default.connection, routing.default.connection)
        model = routing.default.model
    else:
        card, model = secretstore.legacy_default()
        active_provider = _CARD_TO_V1_PROVIDER.get(card, card or "")
    return SettingsStatus(
        encryption_available=secretstore.encryption_available(),
        active_provider=active_provider,
        model=model,
        anthropic_key_set=bool(secretstore.get_connection("claude").get("apiKey")),
        # OpenAI key is set if the codex card has either an api key or a valid
        # oauth subscription — either mode makes the card usable.
        openai_key_set=bool(
            secretstore.get_connection("codex").get("apiKey")
            or secretstore.get_connection("codex").get("oauth", {}).get("accessToken")
        ),
        ollama_host=secretstore.get_connection("ollama").get("baseUrl", ""),
    )


@router.get("/profile", response_model=ProfileStatus)
def profile() -> ProfileStatus:
    return ProfileStatus(has_profile=has_profile())


def _onboarding_state() -> OnboardingState:
    """Build the current onboarding status from provider routing, the profile,
    and the persisted onboarding progress."""
    provider_done = onboarding_store.provider_ready()
    profile_done = has_profile()
    state = onboarding_store.load()
    return OnboardingState(
        provider_done=provider_done,
        has_profile=profile_done,
        cv_reviewed_at=state.cv_reviewed_at,
        tour_seen_at=state.tour_seen_at,
        complete=provider_done and profile_done and state.cv_reviewed_at is not None,
    )


@router.get("/onboarding", response_model=OnboardingState)
def onboarding() -> OnboardingState:
    """First-run onboarding progress: provider setup, profile, CV review, tour."""
    onboarding_store.ensure_initialized()
    return _onboarding_state()


@router.put("/onboarding", response_model=OnboardingState)
def put_onboarding(body: OnboardingUpdate) -> OnboardingState:
    """Merge only the fields the client actually sent onto the stored state."""
    onboarding_store.ensure_initialized()
    merged = onboarding_store.load().to_dict()
    merged.update(body.model_dump(exclude_unset=True, by_alias=False))
    onboarding_store.save(onboarding_store.OnboardingState.from_dict(merged))
    return _onboarding_state()


@router.get("/profile/answers", response_model=AnswersModel)
def get_profile_answers() -> AnswersModel:
    return AnswersModel.model_validate(load_answers().to_dict())


@router.put("/profile/answers", response_model=AnswersModel)
def put_profile_answers(body: AnswersUpdate) -> AnswersModel:
    """Merge only the fields the client actually sent onto the stored answers.

    Omitted fields must survive untouched — the wizard's field-by-field save
    flow means most PUTs carry a strict subset of the 21 fields, and treating
    absence the same as "clear this" would silently blank the rest.
    """
    merged = load_answers().to_dict()
    merged.update(body.model_dump(exclude_unset=True, by_alias=False))
    answers = Answers.from_dict(merged)
    return AnswersModel.model_validate(save_answers(answers).to_dict())


def _resolved_job_boards(cfg: agent_config_store.AgentConfig) -> list[dict]:
    """Build the RESOLVED wire list of job boards from an agent config.

    Both GET and PUT responses go through this helper so they cannot drift.
    Iterates ``cfg.resolved_boards()`` (the four defaults, then the operator's
    own boards, each already carrying its EFFECTIVE mode) and for each board
    emits its stored sign-in override (if any), plus the server-resolved
    domain, effective sign-in URL, default marker and mode. ``mode_locked``
    is True for any catalog source — its mode is fixed and not operator-
    editable — and False only for a custom board. The response deliberately
    carries this resolved list rather than the stored one, so the client
    never re-implements the union — and ``is_default`` is what tells the UI
    to withhold a remove button.
    """
    from agentconfig import boards

    result = []
    for board in cfg.resolved_boards():
        result.append({
            "source": board.source,
            "signin_url": board.signin_url,
            "mode": board.mode,
            "mode_locked": not boards.is_custom_source(board.source),
            "domain": boards.resolve_domain(board.source) or "",
            "effective_signin_url": boards.resolve_signin_url(board.source, board.signin_url),
            "is_default": boards.is_default_source(board.source),
            "is_api": boards.is_api_source(board.source),
        })
    return result


def _fetch_feed_postings(cfg):
    """Pull postings for every API-backed board the operator has configured.

    Only Remote Rocketship exists today; the resolved-source check is what
    keeps it opt-in, so an operator who has not added the board pays no
    request even with a key sitting in secrets.enc. The check goes through
    boards.is_api_source rather than comparing to the catalog key, so a board
    added as a raw domain reaches the feed like any other.
    """
    from agentconfig import boards
    from jobfeeds import remoterocketship

    if not any(boards.is_api_source(source) for source in cfg.resolved_board_sources()):
        return remoterocketship.FeedResult()
    return remoterocketship.fetch_postings(
        cfg.profiles, remoterocketship.api_key(), cfg.max_posting_age_days
    )


@router.get("/job-boards/{source}/key", response_model=JobBoardKeyStatus)
def get_job_board_key(source: str) -> JobBoardKeyStatus:
    """Whether an API-backed board has a key saved. The key itself is never returned."""
    from agentconfig import boards
    from jobfeeds import remoterocketship

    if not boards.is_api_source(source):
        raise HTTPException(status_code=404, detail=f"'{source}' is not an API-backed job board.")
    return JobBoardKeyStatus(
        source=remoterocketship.SOURCE,
        key_set=bool(remoterocketship.api_key()),
        encryption_available=secretstore.encryption_available(),
    )


@router.put("/job-boards/{source}/key", response_model=JobBoardKeyStatus)
def put_job_board_key(source: str, body: JobBoardKeyUpdate) -> JobBoardKeyStatus:
    """Save (or, with an empty string, clear) an API-backed board's key."""
    from agentconfig import boards
    from jobfeeds import remoterocketship

    if not boards.is_api_source(source):
        raise HTTPException(status_code=404, detail=f"'{source}' is not an API-backed job board.")
    if not secretstore.encryption_available():
        raise HTTPException(status_code=400, detail="Set ENCRYPTION_KEY in .env first.")
    value = body.api_key.strip()
    secretstore.set_connection(remoterocketship.SOURCE, {"apiKey": value or None})
    return JobBoardKeyStatus(
        source=remoterocketship.SOURCE,
        key_set=bool(remoterocketship.api_key()),
        encryption_available=True,
    )


@router.post("/job-boards/{source}/key/test", response_model=TestResult)
def test_job_board_key(source: str) -> TestResult:
    """Verify the saved key with one live request against the board's API."""
    from agentconfig import boards
    from jobfeeds import remoterocketship

    if not boards.is_api_source(source):
        raise HTTPException(status_code=404, detail=f"'{source}' is not an API-backed job board.")
    ok, detail = remoterocketship.check_key(remoterocketship.api_key())
    return TestResult(ok=ok, detail=detail)


@router.get("/agent/config", response_model=AgentConfigModel)
def get_agent_config(include_feed: bool = False) -> AgentConfigModel:
    """Fetch agent config with resolved company boards and composed search queries.

    Prunes board entries for companies no longer on the target watchlist.

    ``include_feed`` opts into pulling postings from the configured API-backed
    boards, which means an outbound HTTP call. It is off by default and only
    the agent asks for it: the web UI loads this endpoint on two pages, and
    making every page load wait on a third-party API — or fail with it — is a
    cost paid for nothing, since the browser never renders the postings.
    """
    from companyboards import store as board_store
    from agentconfig.dorks import compose_direct_boards, compose_queries
    
    cfg = agent_config_store.load()
    data = cfg.to_dict()
    
    # Load company boards and prune to target watchlist
    boards_store_boards = board_store.load()
    board_store.prune(cfg.target_companies)
    
    # Populate company_boards in response. Matched by identity key (not raw
    # casefold equality) so a legal-entity suffix on either side does not
    # exclude a board that is really for a target company.
    target_company_keys = {company_identity_key(name) for name in cfg.target_companies}
    data["company_boards"] = [
        {"company": board.company, "careers_url": board.careers_url, "ats": board.ats, "status": board.status, "resolved_at": board.resolved_at}
        for board in boards_store_boards.values()
        if company_identity_key(board.company) in target_company_keys
    ]

    # Populate job_boards with the resolved (defaults-first) list.
    data["job_boards"] = _resolved_job_boards(cfg)

    # Populate search_queries in response. The freshness window is applied to
    # the composed URLs here rather than stored on them, so changing the
    # setting takes effect on the next fetch with no stored state to migrate.
    # resolved_boards() (not resolved_board_sources()) is passed so a
    # direct-mode board is excluded from the dorks rather than defaulting to
    # "dork" the way a bare source string would.
    resolved_boards = cfg.resolved_boards()
    data["search_queries"] = compose_queries(cfg.profiles, cfg.max_posting_age_days, resolved_boards)

    # One entry per direct-mode board, for the agent to search on-site.
    data["direct_boards"] = compose_direct_boards(cfg.profiles, resolved_boards)

    # Postings from API-backed boards, on request only. fetch_postings never
    # raises, so a Remote Rocketship outage degrades this response to the
    # config it always carried rather than failing the agent's config fetch.
    if include_feed:
        feed = _fetch_feed_postings(cfg)
        data["feed_postings"] = [p.to_dict() for p in feed.postings]
        data["feed_error"] = feed.error

    return AgentConfigModel.model_validate(data)


@router.put("/agent/config", response_model=AgentConfigModel)
def put_agent_config(body: AgentConfigUpdate) -> AgentConfigModel:
    """Merge only the fields the client sent onto the stored config.

    Profiles are WHOLESALE-REPLACED (not merged) because a null or omitted
    profiles field never reaches the merge dict. job_boards is replaced the
    same way, but first NORMALISED: the response-only keys (domain,
    effective_signin_url, is_default) are stripped — they are derived, and a
    stored copy is a second writer that can go stale — and any default-source
    entry with a blank signin_url is DROPPED, so a client echoing back the
    resolved GET list does not bloat storage with the four defaults. A
    default-source entry WITH a signin_url is kept, since that is a
    legitimate override.

    The optional numeric windows are the exception to exclude_none: for them a
    null is a real value meaning "unset", and dropping it made those fields
    impossible to clear once set. Emptying the box on the Agents page sends
    null, the merge discarded it, and the UI then repainted the old value
    beside a "saved" indicator. They are re-applied explicitly below, still
    only when the client actually sent the key.
    """
    sent = body.model_dump(exclude_unset=True, by_alias=False)
    saved = agent_config_service.update_agent_config(sent)
    data = saved.to_dict()
    data["job_boards"] = _resolved_job_boards(saved)
    return AgentConfigModel.model_validate(data)


def _claude_credentials(model: str) -> AgentLlmCredentials:
    """Resolve claude card credentials: oauth first, then apikey, else 404/503."""
    conn = secretstore.get_connection("claude")
    oauth = conn.get("oauth") or {}
    if oauth.get("accessToken") and conn.get("authMode") != "apikey":
        try:
            token = get_valid_access_token()
        except AuthError:
            raise HTTPException(
                status_code=503, detail="Claude subscription needs reconnecting."
            ) from None
        return AgentLlmCredentials(
            auth_type="oauth", token=token, model=model,
            provider="claude", wire="anthropic-messages",
        )

    api_key = conn.get("apiKey")
    if api_key:
        return AgentLlmCredentials(
            auth_type="api_key", token=api_key, model=model,
            provider="claude", wire="anthropic-messages",
        )
    raise HTTPException(status_code=404)


def _codex_credentials(model: str) -> AgentLlmCredentials:
    """Resolve codex card credentials: subscription oauth or apikey, OpenAI wire."""
    conn = secretstore.get_connection("codex")
    oauth = conn.get("oauth") or {}
    if oauth.get("accessToken") and conn.get("authMode") != "apikey":
        try:
            token = codex_auth.get_valid_access_token()
        except codex_auth.AuthError:
            raise HTTPException(
                status_code=503, detail="ChatGPT subscription needs reconnecting."
            ) from None
        return AgentLlmCredentials(
            auth_type="oauth", token=token, model=model,
            provider="codex", wire="openai-responses",
        )
    api_key = conn.get("apiKey")
    if not api_key:
        raise HTTPException(status_code=404)
    return AgentLlmCredentials(
        auth_type="api_key", token=api_key, model=model,
        provider="codex", wire="openai-chat-completions",
    )


def _openrouter_credentials(model: str) -> AgentLlmCredentials:
    """Resolve openrouter card credentials: apikey-only, plain OpenAI wire (not
    the Anthropic-compat shim, which is only for the claude CLI)."""
    api_key = secretstore.get_connection("openrouter").get("apiKey")
    if not api_key:
        raise HTTPException(status_code=404)
    return AgentLlmCredentials(
        auth_type="api_key", token=api_key, model=model,
        base_url=OPENROUTER_BASE_URL,
        provider="openrouter", wire="openai-chat-completions",
    )


def _ollama_credentials(model: str) -> AgentLlmCredentials:
    """Resolve ollama card credentials: url-only, no token, OpenAI-shaped wire."""
    base_url = secretstore.get_connection("ollama").get("baseUrl")
    if not base_url:
        raise HTTPException(status_code=404)
    return AgentLlmCredentials(
        auth_type="url", token="", model=model, base_url=base_url,
        provider="ollama", wire="openai-chat-completions",
    )


_CARD_CREDENTIALS = {
    "claude": _claude_credentials,
    "codex": _codex_credentials,
    "openrouter": _openrouter_credentials,
    "ollama": _ollama_credentials,
}


@router.get("/agent/llm-credentials", response_model=AgentLlmCredentials)
def get_agent_llm_credentials(x_agent_token: str = Header(default="")) -> AgentLlmCredentials:
    """Guarded: only the unattended agent (holding AGENT_API_TOKEN) may call this.

    Returns 404 rather than 401/403 so the response carries no authentication hint.
    Serves all four connection cards; the caller picks its wire format from the
    `wire` field on the response rather than assuming Anthropic.
    """
    secret = os.environ.get("AGENT_API_TOKEN", "").strip()
    given = x_agent_token.encode("utf-8", "surrogateescape")
    if not secret or not hmac.compare_digest(given, secret.encode("utf-8")):
        raise HTTPException(status_code=404)

    route = modelrouting.load().agent
    card = route.connection if route else "claude"
    model = route.model if route else ""

    resolve = _CARD_CREDENTIALS.get(card)
    if resolve is None:
        raise HTTPException(status_code=404)
    creds = resolve(model)
    creds.context_window = route.context_window if route else 0
    return creds


def _agent_token_ok(given: str) -> bool:
    """Whether `given` matches AGENT_API_TOKEN. Same rule as
    get_agent_llm_credentials: an unset secret matches nothing."""
    secret = os.environ.get("AGENT_API_TOKEN", "").strip()
    if not secret:
        return False
    return hmac.compare_digest(
        given.encode("utf-8", "surrogateescape"), secret.encode("utf-8")
    )


@router.post("/agent/runs/{run_id}/start", response_model=AgentRunAccountingResult)
def post_agent_run_start(
    run_id: str,
    body: AgentRunStart,
    x_agent_token: str = Header(default=""),
) -> AgentRunAccountingResult:
    """Create the run record for `run_id`, before the run does any work.

    Guarded by AGENT_API_TOKEN and 404 on mismatch, matching
    get_agent_llm_credentials — this writes to the ledger the operator reads,
    so it is deliberately NOT on the unauthenticated /mcp tool surface and is
    not a capability the model can reach.

    Until this existed the only way a run record came into being was the model
    calling the ``start_run`` MCP tool, so a run that failed before its first
    turn — the LLM provider rejecting every attempt, a precondition abort, an
    MCP connection failure — left no trace in Recent runs at all. That is the
    exact case an operator most needs to see.

    ``runs.store.start`` is idempotent, so the model's later ``start_run`` with
    the same id joins this record rather than resetting it.
    """
    if not _agent_token_ok(x_agent_token):
        raise HTTPException(status_code=404)
    runs_store.start(run_id, trigger=body.trigger, apply_cap=body.apply_cap)
    return AgentRunAccountingResult(recorded=True)


@router.post("/agent/runs/{run_id}/finish", response_model=AgentRunAccountingResult)
def post_agent_run_finish(
    run_id: str,
    body: AgentRunFinish,
    x_agent_token: str = Header(default=""),
) -> AgentRunAccountingResult:
    """Close out `run_id` — but only while it is still running.

    The supervisor calls this on every child exit, including the ones no
    in-container code survives (SIGKILL after a cancel, spawn failure). It
    reports ``recorded=False`` when the model's own ``finish_run`` already
    closed the record: that account names where the run actually stopped and
    must win over an exit-code-derived one.
    """
    if not _agent_token_ok(x_agent_token):
        raise HTTPException(status_code=404)
    try:
        record = runs_store.finish_if_running(
            run_id, status=body.status, stopped_reason=body.stopped_reason
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentRunAccountingResult(recorded=record is not None)


def _agent_control_url(path: str) -> str:
    """Build the supervisor.js control URL from env, defaulting port 9099."""
    port = os.environ.get("AGENT_CONTROL_PORT", "9099")
    return f"http://agent:{port}{path}"


def _forward_to_supervisor(path: str, method: str = "GET") -> dict:
    """Forward a request to the agent supervisor.js control server.

    Raises HTTPException(503) when the agent is unreachable, 502 when it
    answered with an error status (403 = token mismatch), and 500 when this
    service has no AGENT_API_TOKEN to send. These are kept distinct on purpose:
    they have three different fixes and used to share one message.
    """
    token = os.environ.get("AGENT_API_TOKEN", "").strip()
    # An unset shared secret is not a network problem and never becomes one by
    # retrying: the supervisor rejects every request and the operator has no
    # way to tell that from a container that is down. Fail here, before the
    # dial, so the message names the actual cause.
    if not token:
        raise HTTPException(
            status_code=500,
            detail=(
                "AGENT_API_TOKEN is not set on the app service, so the agent "
                "will reject every request. Set it in .env (the same value for "
                "app, agent and browser) and restart the stack."
            ),
        )

    url = _agent_control_url(path)
    req = urllib.request.Request(
        url,
        method=method,
        headers={"X-Agent-Token": token},
        data=b"" if method == "POST" else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        # MUST be caught before URLError: HTTPError subclasses it, so a single
        # URLError handler renders a 403 as "Agent service unreachable" — the
        # one message that sends the operator to look at the network when the
        # supervisor answered perfectly well and refused the token.
        if exc.code in (401, 403):
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Agent service refused the request (HTTP {exc.code}): the app "
                    "and the agent container disagree on AGENT_API_TOKEN. Make both "
                    "match in .env and restart the stack."
                ),
            ) from exc
        raise HTTPException(
            status_code=502,
            detail=f"Agent service returned HTTP {exc.code} for {path}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=503, detail="Agent service unreachable") from exc


@router.get("/agent/status", response_model=AgentStatus)
def get_agent_status() -> AgentStatus:
    """Return the agent supervisor's running/idle state.

    Forwards to supervisor.js GET /status over the compose network.
    Returns 503 when the agent container is unreachable, 502 when it answers
    with an error (403 = AGENT_API_TOKEN mismatch).
    """
    data = _forward_to_supervisor("/status", method="GET")
    return AgentStatus(
        running=data.get("running", False),
        cancelling=data.get("cancelling", False),
        last_started_at=data.get("lastStartedAt"),
        last_finished_at=data.get("lastFinishedAt"),
        last_exit_code=data.get("lastExitCode"),
        last_cancelled=data.get("lastCancelled", False),
        # Absent on an older supervisor image — .get() defaults to None rather
        # than raising, so this route does not 500 against one.
        current_run_id=data.get("currentRunId"),
        last_run_id=data.get("lastRunId"),
    )


@router.post("/agent/run", response_model=AgentRunResult)
def post_agent_run() -> AgentRunResult:
    """Trigger an immediate agent run via the supervisor control server.

    Fire-and-forget: returns as soon as the supervisor acknowledges the
    trigger — does NOT wait for the run to complete. Returns 503 when the
    agent container is unreachable.
    """
    data = _forward_to_supervisor("/run", method="POST")
    return AgentRunResult(
        started=data.get("started", False),
        running=data.get("running", False),
    )


@router.post("/agent/cancel", response_model=AgentCancelResult)
def post_agent_cancel() -> AgentCancelResult:
    """Stop the run in progress via the supervisor control server.

    Fire-and-forget, like the trigger: the supervisor signals the run's process
    group and answers immediately, so the run may still be tearing down when
    this returns. Poll GET /api/agent/status for the transition to idle.
    Returns 503 when the agent container is unreachable, 502 when it answers
    with an error (403 = AGENT_API_TOKEN mismatch).
    """
    data = _forward_to_supervisor("/cancel", method="POST")
    return AgentCancelResult(
        cancelled=data.get("cancelled", False),
        running=data.get("running", False),
    )


def _host_of(url: str) -> str:
    """The full host of an absolute http(s) URL, or "" if it is not one.

    Anything without a scheme and a netloc is not addressable, so it cannot be
    a sign-in destination — returning "" drops it rather than grouping several
    unrelated records under a blank host.
    """
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return parsed.netloc.casefold()


@router.get("/browser/signin-queue", response_model=SigninQueue)
def get_signin_queue() -> SigninQueue:
    """Sites the agent hit a sign-in wall on, grouped by host.

    Derived from the screening store on every call rather than kept as its own
    state: the agent's experience is the only source of truth here, so an entry
    exists exactly as long as a posting is still waiting behind that sign-in.
    """
    grouped: dict[str, dict] = {}
    for s in screening_store.load_all():
        if s.apply_blocker != "login_required":
            continue
        # Only items still queued to be applied to. Applied or rejected means
        # nothing is waiting on this sign-in any more.
        if s.approval not in ("pending", "approved"):
            continue
        url = s.signin_url or s.url
        host = _host_of(url)
        if not host:
            continue
        entry = grouped.setdefault(
            host,
            {"host": host, "signin_url": url, "waiting": 0, "last_blocked_at": "", "companies": []},
        )
        entry["waiting"] += 1
        if s.updated_at > entry["last_blocked_at"]:
            entry["last_blocked_at"] = s.updated_at
        if s.company and s.company not in entry["companies"]:
            entry["companies"].append(s.company)
    sites = [SigninQueueSite(**e) for e in grouped.values()]
    sites.sort(key=lambda s: (-s.waiting, s.host))
    return SigninQueue(sites=sites)


def _browser_control_url(path: str) -> str:
    """Build the session-server control URL from env, defaulting port 8932."""
    port = os.environ.get("SESSION_SERVER_PORT", "8932")
    return f"http://browser:{port}{path}"


def _forward_to_session_server(path: str, method: str = "GET", body: dict | None = None) -> dict:
    """Forward a request to browser/session-server.js.

    Distinguishes three outcomes the UI must tell apart: a normal answer, a
    refusal the session server made deliberately (4xx/503 — forwarded with its
    own status so "the agent is applying right now" does not read as "the
    browser is broken"), and the container being unreachable (503).
    """
    token = os.environ.get("AGENT_API_TOKEN", "")
    data = json.dumps(body or {}).encode() if method == "POST" else None
    req = urllib.request.Request(
        _browser_control_url(path),
        method=method,
        headers={"X-Agent-Token": token, "Content-Type": "application/json"},
        data=data,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        # Forward the session server's own refusal payload. It distinguishes
        # session_open (which carries the already-open session's URL, so the UI
        # can offer to return to it) from agent_running and profile_busy — all
        # three are 409s that call for different words on screen.
        try:
            detail = json.loads(exc.read())
        except (ValueError, OSError):
            detail = {"reason": "refused"}
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=503, detail="Browser service unreachable") from exc


def _session_from(data: dict) -> BrowserSession:
    return BrowserSession(
        open=data.get("open", False),
        url=data.get("url"),
        started_at=data.get("startedAt"),
        evict_deadline=data.get("evictDeadline"),
    )


@router.get("/browser/session", response_model=BrowserSession)
def get_browser_session() -> BrowserSession:
    """Whether an attended sign-in session is open, and at which URL."""
    return _session_from(_forward_to_session_server("/session", method="GET"))


@router.post("/browser/session", response_model=BrowserSession)
def post_browser_session(payload: BrowserSessionRequest) -> BrowserSession:
    """Open an attended sign-in session at a URL.

    Refused with 409 while a run is in progress: unattended runs win, and the
    operator is told to try again shortly rather than the run being disturbed.
    """
    if _host_of(payload.url) == "":
        raise HTTPException(status_code=422, detail="An http(s) URL is required")
    return _session_from(
        _forward_to_session_server("/session", method="POST", body={"url": payload.url})
    )


@router.delete("/browser/session", response_model=BrowserSessionClosed)
def delete_browser_session() -> BrowserSessionClosed:
    """Close the attended session and release the browser.
    
    When closing a session, re-arm any login-blocked items whose host matches
    the closed session's URL, so they re-enter the queue for the next run.
    """
    # Read the current session URL before closing it
    session_data = _forward_to_session_server("/session")
    session_url = session_data.get("url", "")
    
    # Forward the close request
    data = _forward_to_session_server("/session/close", method="POST")
    
    signins_cleared = 0
    # Only clear blockers if the session existed and the close was accepted
    if session_url and (data.get("closed", False) or data.get("closing", False)):
        # Clear login blockers for this host
        host = _host_of(session_url)
        if host:
            signins_cleared = screenings_service.clear_login_blockers_for_host(host)
    
    return BrowserSessionClosed(
        closed=data.get("closed", False),
        closing=data.get("closing", False),
        reserving=data.get("reserving", False),
        signins_cleared=signins_cleared,
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
            tone=body.tone,
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
    )


@router.get("/settings", response_model=SettingsStatus)
def get_settings() -> SettingsStatus:
    return _settings_status()


@router.post("/settings", response_model=SettingsStatus)
def post_settings(body: SettingsUpdate) -> SettingsStatus:
    """Old single-provider POST shape, shimmed onto the v2 store: the key/host
    lands in that provider's connection, and {connection, model} becomes the
    routing default."""
    if not secretstore.encryption_available():
        raise HTTPException(status_code=400, detail="Set ENCRYPTION_KEY in .env first.")
    card = _V1_PROVIDER_TO_CARD.get(body.active_provider, body.active_provider)
    if card not in catalog.CARDS:
        raise HTTPException(
            status_code=400, detail=f"Unknown provider '{body.active_provider}'."
        )

    updates: dict = {}
    if body.api_key:  # empty/None leaves the stored key unchanged
        updates["apiKey"] = body.api_key
    if body.ollama_host:
        updates["baseUrl"] = body.ollama_host
    if updates:
        secretstore.set_connection(card, updates)

    routing = modelrouting.load()
    if body.model is not None:
        model = body.model
    else:
        model = routing.default.model if routing.default else ""
    routing.default = modelrouting.Route(card, model)
    modelrouting.save(routing)

    reset_provider()
    return _settings_status()


@router.post("/settings/test", response_model=TestResult)
def test_settings(body: SettingsUpdate) -> TestResult:
    try:
        post_settings(body)
        provider = get_provider(refresh=True)
        provider.complete("ping", [{"role": "user", "content": "ping"}])
        return TestResult(ok=True, detail="Connection succeeded.")
    except HTTPException as e:
        return TestResult(ok=False, detail=str(e.detail))
    except Exception as e:  # noqa: BLE001
        return TestResult(ok=False, detail=f"{type(e).__name__}: {e}")


def _provider_from_update(body: SettingsUpdate):
    """Build a provider from the submitted settings WITHOUT persisting anything.

    Uses a key/host typed in the form if present, otherwise the saved connection
    — so the model list can load with an unsaved key (like Test connection) and
    without writing secrets just to populate a dropdown.
    """
    name = (body.active_provider or "").strip().lower()
    card = _V1_PROVIDER_TO_CARD.get(name)
    if card is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{name}'.")
    conn = secretstore.get_connection(card)
    if card == "claude":
        from providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=body.api_key or conn.get("apiKey") or None)
    if card == "codex":
        from providers.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=body.api_key or conn.get("apiKey") or None)
    if card == "ollama":
        from providers.ollama_provider import OllamaProvider

        return OllamaProvider(host=body.ollama_host or conn.get("baseUrl") or None)
    raise HTTPException(status_code=400, detail=f"Unknown provider '{name}'.")


@router.post("/models", response_model=ModelList)
def list_models(body: SettingsUpdate) -> ModelList:
    """Live model list for the selected provider, pulled from its API/SDK."""
    name = (body.active_provider or "").strip().lower()
    card = _V1_PROVIDER_TO_CARD.get(name, "")
    try:
        provider = _provider_from_update(body)
        models = provider.list_models()
    except HTTPException:
        raise
    except ProviderError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}") from e
    return _models_result(models, card)


def _require_card(provider: str) -> dict:
    try:
        return catalog.card(provider)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown connection '{provider}'.") from None


def _connection_status(card_key: str) -> ConnectionStatus:
    meta = catalog.card(card_key)
    conn = secretstore.get_connection(card_key)
    oauth = conn.get("oauth") or {}
    has_key = bool(conn.get("apiKey")) or (card_key == "ollama" and bool(conn.get("baseUrl")))
    return ConnectionStatus(
        provider=card_key,
        label=meta["label"],
        modes=list(meta["modes"]),
        subscription_connected=bool(oauth.get("accessToken")),
        api_key_connected=has_key,
        auth_mode=conn.get("authMode", ""),
        expires_at=oauth.get("expiresAt"),
        connected_at=oauth.get("connectedAt"),
    )


def _models_result(models: list[dict], provider_key: str = "") -> ModelList:
    """Build a ModelList, annotating each entry with its supported effort levels."""
    return ModelList(
        models=[
            ModelInfo(
                id=m["id"],
                label=m.get("label") or m["id"],
                effort_levels=supports_effort_levels(provider_key, m["id"]),
            )
            for m in models
        ]
    )


@router.get("/auth/status", response_model=ConnectionList)
def get_connection_status() -> ConnectionList:
    return ConnectionList(
        encryption_available=secretstore.encryption_available(),
        connections=[_connection_status(key) for key in catalog.card_keys()],
    )


# Card -> auth module registry
_AUTH_MODULES = {"claude": claude_auth, "codex": codex_auth}


@router.post("/auth/{provider}/start", response_model=StartLoginResult)
def start_connection_login(provider: str) -> StartLoginResult:
    _require_card(provider)
    if provider not in _AUTH_MODULES:
        raise HTTPException(
            status_code=400,
            detail=f"Subscription sign-in is not available for '{provider}'.",
        )
    try:
        return StartLoginResult.model_validate(_AUTH_MODULES[provider].start_login())
    except (claude_auth.AuthError, codex_auth.AuthError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# Specific route must come BEFORE the generic /{provider}/complete to avoid
# FastAPI matching /api/auth/claude/complete against the general pattern.
@router.post("/auth/claude/complete", response_model=ConnectionStatus)
def complete_claude_login_alias(body: CompleteLoginRequest) -> ConnectionStatus:
    """Deprecated: delegates to the generic /complete handler. Retained so a
    deployed web bundle from before this change does not break mid-deploy."""
    return _complete_login("claude", body)


@router.post("/auth/{provider}/complete", response_model=ConnectionStatus)
def _complete_login(provider: str, body: CompleteLoginRequest) -> ConnectionStatus:
    if provider not in _AUTH_MODULES:
        raise HTTPException(status_code=404, detail=f"Unknown connection '{provider}'.")
    try:
        _AUTH_MODULES[provider].complete_login(body.code)
    except (claude_auth.AuthError, codex_auth.AuthError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    reset_provider()
    return _connection_status(provider)


@router.post("/auth/{provider}/poll", response_model=PollLoginResult)
def _poll_login(provider: str) -> PollLoginResult:
    if provider not in _AUTH_MODULES:
        raise HTTPException(status_code=404, detail=f"Unknown connection '{provider}'.")
    mod = _AUTH_MODULES[provider]
    if not hasattr(mod, "poll_login"):
        raise HTTPException(status_code=400, detail=f"Provider '{provider}' does not support polling.")
    try:
        result = mod.poll_login()
    except (claude_auth.AuthError, codex_auth.AuthError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if result.get("status") == "complete":
        return PollLoginResult(
            status="complete",
            connected_at=result.get("connectedAt"),
            expires_at=result.get("expiresAt"),
            scope=result.get("scope"),
        )
    return PollLoginResult(
        status="pending",
        interval_seconds=result.get("intervalSeconds"),
    )


def _probe_key(card: str, body: ApiKeyRequest) -> list[dict]:
    """Construct a provider directly from the submitted credential (never via
    the stored oauth path) and list its models. An empty submitted value falls
    back to the currently stored credential, so a bare re-validate still works."""
    conn = secretstore.get_connection(card)
    if card == "claude":
        from providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(api_key=body.api_key or conn.get("apiKey") or None)
    elif card in ("codex", "openrouter"):
        from providers.openai_provider import OpenAIProvider

        base_url = OPENROUTER_BASE_URL if card == "openrouter" else None
        provider = OpenAIProvider(
            api_key=body.api_key or conn.get("apiKey") or None, base_url=base_url
        )
    elif card == "ollama":
        from providers.ollama_provider import OllamaProvider

        provider = OllamaProvider(
            host=body.base_url or conn.get("baseUrl") or None,
            bearer=body.bearer or conn.get("bearer") or None,
        )
    else:
        raise ProviderError(f"Unknown connection '{card}'.")
    return provider.list_models()


@router.post("/auth/{provider}/key", response_model=ModelList)
def post_connection_key(provider: str, body: ApiKeyRequest) -> ModelList:
    _require_card(provider)
    if not secretstore.encryption_available():
        raise HTTPException(status_code=400, detail="Set ENCRYPTION_KEY in .env first.")
    try:
        models = _probe_key(provider, body)
    except ProviderError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 — surface upstream SDK auth errors as 400s
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}") from e
    updates: dict = {}
    if body.api_key:
        updates["apiKey"] = body.api_key
    if body.base_url:
        updates["baseUrl"] = body.base_url
    if body.bearer:
        updates["bearer"] = body.bearer
    if body.api_key and "subscription" in catalog.card(provider)["modes"]:
        updates["authMode"] = "apikey"
    if updates:
        secretstore.set_connection(provider, updates)
    reset_provider()
    return _models_result(models, provider)


@router.get("/auth/{provider}/models", response_model=ModelList)
def get_connection_models(provider: str) -> ModelList:
    _require_card(provider)
    try:
        models = build_connection_provider(provider, None).list_models()
    except ProviderError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 — surface upstream LLM/SDK errors cleanly
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}") from e
    return _models_result(models, provider)


@router.post("/auth/{provider}/test", response_model=TestResult)
def test_connection(provider: str, body: ConnectionTestRequest) -> TestResult:
    _require_card(provider)
    try:
        provider_obj = build_connection_provider(provider, body.model)
        provider_obj.complete("ping", [{"role": "user", "content": "ping"}])
        return TestResult(ok=True, detail="Connection succeeded.")
    except HTTPException as e:
        return TestResult(ok=False, detail=str(e.detail))
    except Exception as e:  # noqa: BLE001
        return TestResult(ok=False, detail=f"{type(e).__name__}: {e}")


@router.post("/auth/{provider}/logout", response_model=ConnectionStatus)
def logout_connection(provider: str, mode: str | None = None) -> ConnectionStatus:
    """Disconnect `provider`, defaulting to the card's currently active mode.

    Without an explicit `mode`, we clear whichever mode is currently active
    (oauth or apikey), so the card no longer reports a connection in either
    mode. Passing `mode` clears just that mode and leaves the other intact —
    that is the same semantics the existing per-mode logout tests pin.
    """
    _require_card(provider)
    if mode is not None:
        secretstore.clear_mode(provider, mode)
    else:
        conn = secretstore.get_connection(provider)
        # Pick the mode that is actually active: subscription if oauth is set,
        # otherwise apikey. clear_mode is a no-op on the missing side.
        active = "subscription" if conn.get("oauth", {}).get("accessToken") else "apikey"
        secretstore.clear_mode(provider, active)
    reset_provider()
    return _connection_status(provider)


@router.get("/routing", response_model=RoutingModel)
def get_routing() -> RoutingModel:
    """Get the current model routing configuration."""
    routing = modelrouting.load()
    return RoutingModel(
        tasks={k: _route_model(v) for k, v in routing.tasks.items()},
        agent=_route_model(routing.agent) if routing.agent else None,
        default=_route_model(routing.default) if routing.default else None,
    )


@router.put("/routing", response_model=RoutingModel)
def put_routing(body: RoutingUpdate) -> RoutingModel:
    """Merge only the fields the client sent onto the stored routing.

    A field explicitly sent as null is not the same as an absent field: it
    clears that route (`default`/`agent` sent as null, or a `tasks` entry
    sent as null, removes it) instead of leaving the stored value untouched.
    """
    # Load current routing
    stored = modelrouting.load()
    stored_dict = stored.to_dict()

    # Prepare update from body — exclude_unset only, so an explicit null
    # survives into update_dict and is distinguishable from an absent field.
    update_dict = body.model_dump(exclude_unset=True, by_alias=False)

    # Validate all connections and effort levels in the update before applying
    for route_dict in _all_routes_in_dict(update_dict):
        connection = route_dict.get("connection")
        if connection not in catalog.CARDS:
            raise HTTPException(status_code=400, detail=f"unknown connection: {connection}")
        effort = route_dict.get("effort", "")
        if effort and not supports_effort_levels(connection, route_dict.get("model", "")):
            raise HTTPException(
                status_code=400,
                detail=f"effort '{effort}' is not supported for {connection}/{route_dict.get('model', '')}",
            )
        context_window = route_dict.get("context_window", 0)
        if context_window < 0 or 0 < context_window < 8192:
            raise HTTPException(
                status_code=400,
                detail="context_window must be 0 or at least 8192",
            )

    # Merge: update the stored dict with only the fields that were sent.
    # A None value clears the corresponding route rather than being ignored.
    if "tasks" in update_dict:
        for name, route in (update_dict["tasks"] or {}).items():
            if route is None:
                stored_dict["tasks"].pop(name, None)
            else:
                stored_dict["tasks"][name] = route
    if "agent" in update_dict:
        stored_dict["agent"] = update_dict["agent"]
    if "default" in update_dict:
        stored_dict["default"] = update_dict["default"]

    # Parse back to Routing and save
    routing = modelrouting.Routing.from_dict(stored_dict)
    modelrouting.save(routing)
    reset_provider()

    # Return fresh routing
    return RoutingModel(
        tasks={k: _route_model(v) for k, v in routing.tasks.items()},
        agent=_route_model(routing.agent) if routing.agent else None,
        default=_route_model(routing.default) if routing.default else None,
    )


def _all_routes_in_dict(d: dict) -> list[dict]:
    """Collect all route dicts from a routing update dict."""
    routes = []
    if "agent" in d and isinstance(d["agent"], dict):
        routes.append(d["agent"])
    if "default" in d and isinstance(d["default"], dict):
        routes.append(d["default"])
    if "tasks" in d and isinstance(d["tasks"], dict):
        for route in d["tasks"].values():
            if isinstance(route, dict):
                routes.append(route)
    return routes


def _route_model(route: modelrouting.Route) -> RouteModel:
    """Convert a stored Route to its API wire model."""
    return RouteModel(
        connection=route.connection,
        model=route.model,
        effort=route.effort,
        context_window=route.context_window,
    )
