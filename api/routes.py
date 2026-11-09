"""Wizard REST routes wired to the backend modules.

The one hard rule lives in /api/render: the guardrail runs BEFORE any file is
produced, and if it fails nothing is rendered — the response is blocked=true with
the unverifiable tokens.
"""

from __future__ import annotations

import asyncio
import hmac
import importlib
import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse

from providers import ProviderError, get_provider
from truth import load, save
from truth.answers import load as load_answers
from services.inferences import confirm_inferences as confirm_inferences_service
import services.screenings as screenings_service
import services.screening_letters as screening_letters_service
import services.agent_config as agent_config_service
import services.agent_credentials as agent_credentials_service
import services.applications as applications_service
import services.runs as runs_service
import services.supervisor as supervisor_service
import services.settings as settings_service
import services.truth as truth_service
import services.onboarding as onboarding_service
import services.tailor as tailor_service
from services.errors import BadGateway
import services.connections as connections_service
from truth.model import Truth
from truth.pdf import has_profile

import applications as app_store
import modelrouting
import secretstore
from services.render_cv import (
    DraftMissing,
    _claim_id,
    _require_application,
    render_cv,
)
from services.cover_letter import generate_cover_letter
from agentconfig import store as agent_config_store
from connections import catalog
from connections.auth import gmail as gmail_auth
from providers import (
    ANTHROPIC_COMPAT_OPENROUTER_BASE_URL,
    build_connection_provider,
)
from providers.base import supports_effort_levels
from companyresearch import store as company_findings_store
from screening import store as screening_store
from runs import store as runs_store
from identity.company import company_identity_key
from screening.cooldown import cooldown as check_cooldown
from screening.model import Screening

import coverletter.store as letter_store

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
    AgentLlmTokenRefresh,
    AgentLlmTokenResult,
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
    CoverLetterRequest,
    CooldownResult,
    CoverLetterResult,
    GmailStatusModel,
    GmailSyncRequest,
    JevSettingsStatus,
    JevSettingsUpdate,
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
    CategoryCountModel,
    RejectedScreeningModel,
    RejectedScreeningsResponse,
    RouteModel,
    RunListResponse,
    UrlLedgerResponse,
    RunModel,
    RunStopResult,
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

logger = logging.getLogger(__name__)


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
    runs, total = runs_service.list_runs_page(limit, offset)
    return RunListResponse(
        runs=[RunModel(**r) for r in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=RunModel)
def get_run(run_id: str) -> RunModel:
    """A single run record, or 404 if no run with this id has been recorded."""
    return RunModel(**runs_service.get_run(run_id))


# Page size bounds for GET /runs/{run_id}/urls.
URL_LEDGER_DEFAULT_LIMIT = runs_service.URL_LEDGER_DEFAULT_LIMIT
URL_LEDGER_MAX_LIMIT = runs_service.URL_LEDGER_MAX_LIMIT


@router.get("/runs/{run_id}/urls", response_model=UrlLedgerResponse)
def get_run_urls(
    run_id: str,
    source: str = "",
    outcome: str = "",
    limit: int = URL_LEDGER_DEFAULT_LIMIT,
    offset: int = 0,
    channel: str = "",
) -> UrlLedgerResponse:
    """One page of the run's URL ledger, optionally filtered by source and
    outcome. 404 for an unknown run, 400 for an unknown outcome; limit is
    clamped to 1..URL_LEDGER_MAX_LIMIT and a negative offset to 0."""
    entries, total = runs_service.url_ledger_page(
        run_id, source, outcome, limit, offset, channel
    )
    return UrlLedgerResponse(entries=entries, total=total)


@router.post("/runs/{run_id}/stop", response_model=RunStopResult)
def post_run_stop(run_id: str) -> RunStopResult:
    """Stop a run: cancel it through the supervisor if it owns the run, or
    close an orphaned record as failed/orphaned otherwise.
    """
    outcome, run = runs_service.stop_run(run_id)
    return RunStopResult(outcome=outcome, run=RunModel(**run))


def reconcile_orphaned_runs() -> list:
    """Reconcile orphaned runs at API startup (delegates to services.runs)."""
    return runs_service.reconcile_orphaned_runs()


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


def _company_finding_model(f) -> CompanyFindingModel:
    """Map a stored CompanyFinding to its wire model."""
    return CompanyFindingModel(
        **f.to_dict(), company_key=company_identity_key(f.company)
    )


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
        groups = company_findings_store.all_open_contradictions()
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
            claim_label=body.claim_label,
            supersedes=body.supersedes,
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
    await asyncio.to_thread(truth_service.ingest_upload, file.filename or "", data)


@router.post("/extract", response_model=TruthDoc)
def extract() -> TruthDoc:
    try:
        provider = get_provider("truth_extract")
    except ProviderError as e:
        raise BadGateway(str(e)) from e
    except Exception as e:  # noqa: BLE001 — surface upstream LLM/SDK errors cleanly
        raise BadGateway(
            f"The language model call failed: {type(e).__name__}: {e}"
        ) from e
    return _truth_doc(truth_service.extract_truth(provider))


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
    result = tailor_service.tailor_posting(body.posting, get_provider)
    return TailorResult.model_validate(result)


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


@router.put("/applications/{app_id}/cv", response_model=SaveDocumentResult)
def save_application_cv(app_id: str, body: SaveCvRequest) -> SaveDocumentResult:
    """Render and save edited CV HTML onto an application.

    A manual edit is a deliberate human decision, so it is trusted and saved
    as-is — the truthfulness guardrail only gates the automatic AI generation
    (/render, /tailor), not a document the user edited by hand.
    """
    app, produced = applications_service.save_cv(app_id, body.html)
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
    app, produced = applications_service.save_cover_letter(app_id, body.text)
    return SaveDocumentResult(
        blocked=False,
        application=_application_model(app),
        render_unavailable=not produced,
    )


@router.get("/profile", response_model=ProfileStatus)
def profile() -> ProfileStatus:
    return ProfileStatus(has_profile=has_profile())


@router.get("/onboarding", response_model=OnboardingState)
def onboarding() -> OnboardingState:
    """First-run onboarding progress: provider setup, profile, CV review, tour."""
    return OnboardingState(**onboarding_service.get_state())


@router.put("/onboarding", response_model=OnboardingState)
def put_onboarding(body: OnboardingUpdate) -> OnboardingState:
    """Merge only the fields the client actually sent onto the stored state."""
    sent = body.model_dump(exclude_unset=True, by_alias=False)
    return OnboardingState(**onboarding_service.update_state(sent))


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
    sent = body.model_dump(exclude_unset=True, by_alias=False)
    return AnswersModel.model_validate(truth_service.update_answers(sent).to_dict())


def _target_company_boards(cfg: agent_config_store.AgentConfig) -> list:
    """Recorded company boards pruned to the current watchlist.

    Matched by identity key (not raw casefold equality) so a legal-entity
    suffix on either side does not exclude a board that is really for a
    target company. Shared by ``get_agent_config``'s ``company_boards``
    response field and ``_fetch_feed_postings``'s ATS fan-out, so the two
    never drift onto different prunings of the same store.
    """
    from companyboards import store as board_store

    boards_store_boards = board_store.load()
    board_store.prune(cfg.target_companies)
    target_company_keys = {company_identity_key(name) for name in cfg.target_companies}
    return [
        board for board in boards_store_boards.values()
        if company_identity_key(board.company) in target_company_keys
    ]


def _merge_feed_results(*results):
    """Merge several ``FeedResult``s into one, de-duplicated by URL.

    One source failing must not empty out a working one, so every result's
    postings are kept regardless of whether that same result also carries an
    error; the errors themselves are joined so a simultaneous failure of more
    than one source is not silently reduced to just the first.
    """
    from jobfeeds import FeedResult

    postings = []
    seen_urls = set()
    errors = []
    for result in results:
        for posting in result.postings:
            if posting.url and posting.url not in seen_urls:
                seen_urls.add(posting.url)
                postings.append(posting)
        if result.error:
            errors.append(result.error)
    return FeedResult(postings=postings, error=" ".join(errors))


# Combined wall-clock ceiling for the Remote Rocketship, Arbeitnow AND
# per-company ATS fetches TOGETHER, not each source's own separate budget.
# agent/agent-config.js gives the job_config request a fixed 30s socket
# timeout and treats a timeout as a hard failure: it destroys the request and
# calls process.exit(1), discarding the whole config — profiles, feed,
# company boards, and dorks. Each fetcher's own BUDGET_SECONDS (20.0s) was
# sized on the assumption it was the ONLY fetch running; fanning out to three
# independent fetchers with independent budgets can now approach 60s.
# Threading this ONE shared deadline into every caller instead keeps them
# together under a single ceiling: whatever the earlier fetchers spend comes
# out of what the others are given. 25s leaves 5s of headroom under the 30s
# socket timeout for the rest of the config route's own work.
FEED_FETCH_BUDGET_SECONDS = 25.0


def _fetch_feed_postings(cfg: agent_config_store.AgentConfig, company_boards: list):
    """Pull postings from Remote Rocketship, Arbeitnow, and every watchlist
    company's own ATS API, whichever apply.

    Fans out across three independent sources and merges them, de-duplicated
    by URL (see ``_merge_feed_results``):

    - Remote Rocketship, gated on a resolved board naming it specifically
      (via ``boards.api_source_key``, not the broader ``is_api_source`` —
      Arbeitnow is also API-backed and always present as a default, and must
      not switch Remote Rocketship on) plus its saved key.
    - Arbeitnow, an always-on default board (agentconfig.boards.DEFAULT_BOARD_SOURCES)
      with a public API — gated the same way on a resolved board naming it,
      but never needs a key.
    - Each watchlist company's own ATS API (jobfeeds.ats), gated only on that
      company's ``CompanyBoard.ats`` naming a recognised ATS — no key needed.

    No fetcher ever raises, and this function does not either: a source that
    fails degrades the merged ``error`` rather than emptying the response,
    while the other sources' postings still arrive.

    All three fetches share ONE wall-clock deadline (FEED_FETCH_BUDGET_SECONDS)
    instead of each getting its own — see that constant's comment for why.
    They also run on their own threads instead of one after another, so the
    slowest of the three governs the wall-clock cost of this function rather
    than their sum; the shared deadline still bounds each individually
    exactly as when they ran serially.
    """
    import threading
    import time

    from agentconfig import boards
    from jobfeeds import arbeitnow, ats, remoterocketship

    deadline = time.monotonic() + FEED_FETCH_BUDGET_SECONDS
    results: dict = {}
    resolved_sources = cfg.resolved_board_sources()

    def _run_remote_rocketship() -> None:
        if any(boards.api_source_key(source) == remoterocketship.SOURCE for source in resolved_sources):
            results["rr"] = remoterocketship.fetch_postings(
                cfg.profiles, remoterocketship.api_key(), cfg.max_posting_age_days, deadline=deadline
            )
        else:
            results["rr"] = remoterocketship.FeedResult()

    def _run_arbeitnow() -> None:
        if any(boards.api_source_key(source) == arbeitnow.SOURCE for source in resolved_sources):
            results["arbeitnow"] = arbeitnow.fetch_postings(
                cfg.profiles, cfg.max_posting_age_days, deadline=deadline
            )
        else:
            results["arbeitnow"] = arbeitnow.FeedResult()

    def _run_ats() -> None:
        results["ats"] = ats.fetch_ats_postings(company_boards, cfg.max_posting_age_days, deadline=deadline)

    threads = [
        threading.Thread(target=_run_remote_rocketship),
        threading.Thread(target=_run_arbeitnow),
        threading.Thread(target=_run_ats),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    return _merge_feed_results(results["rr"], results["arbeitnow"], results["ats"])


@router.get("/job-boards/{source}/key", response_model=JobBoardKeyStatus)
def get_job_board_key(source: str) -> JobBoardKeyStatus:
    """Whether an API-backed board has a key saved. The key itself is never returned."""
    from agentconfig import boards
    from jobfeeds import remoterocketship

    if not boards.requires_key(source):
        raise HTTPException(status_code=404, detail=f"'{source}' is not an API-backed job board that needs a key.")
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

    if not boards.requires_key(source):
        raise HTTPException(status_code=404, detail=f"'{source}' is not an API-backed job board that needs a key.")
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

    if not boards.requires_key(source):
        raise HTTPException(status_code=404, detail=f"'{source}' is not an API-backed job board that needs a key.")
    ok, detail = remoterocketship.check_key(remoterocketship.api_key())
    return TestResult(ok=ok, detail=detail)


@router.get("/settings/jev", response_model=JevSettingsStatus)
def get_jev_settings() -> JevSettingsStatus:
    """Whether Jev cross-checking is configured. The key itself is never returned."""
    return JevSettingsStatus(**settings_service.jev_status())


@router.put("/settings/jev", response_model=JevSettingsStatus)
def put_jev_settings(body: JevSettingsUpdate) -> JevSettingsStatus:
    """Save (or, with an empty string, clear) the Jev API key and/or the
    useForScreening / useForEmailTracking toggles. Saving a non-empty key
    requires encryption."""
    status = settings_service.update_jev(
        body.api_key, body.use_for_screening, body.use_for_email_tracking
    )
    return JevSettingsStatus(**status)


@router.post("/settings/jev/test", response_model=TestResult)
def test_jev_settings() -> TestResult:
    """Verify the saved Jev key with one live request."""
    from screening import jev

    ok, detail = jev.check_key(secretstore.get_connection("jev").get("apiKey", ""))
    return TestResult(ok=ok, detail=detail)


def require_gmail_tracking_enabled() -> None:
    """Raise 403 unless Gmail response-tracking is configured and opted in.

    Gated on the same secretstore "jev" record as Jev screening cross-checks:
    a non-empty apiKey AND useForEmailTracking set to True. Gmail sync
    auto-applies Jev-confirmed transitions, so it must never run on a bare
    Gmail connection without this explicit opt-in.
    """
    conn = secretstore.get_connection("jev")
    if not conn.get("apiKey") or conn.get("useForEmailTracking") is not True:
        raise HTTPException(
            status_code=403,
            detail="Gmail response-tracking requires a saved Jev API key and useForEmailTracking enabled.",
        )


@router.post("/auth/gmail/start", response_model=StartLoginResult)
def start_gmail_login(request: Request) -> StartLoginResult:
    """Begin the Gmail OAuth flow. Gated on the useForEmailTracking opt-in."""
    require_gmail_tracking_enabled()
    redirect_uri = gmail_auth.redirect_uri_override() or str(request.url_for("gmail_callback"))
    try:
        return StartLoginResult.model_validate(gmail_auth.start_login(redirect_uri))
    except gmail_auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/auth/gmail/callback", name="gmail_callback")
def complete_gmail_login(
    code: str | None = None, state: str | None = None, error: str | None = None
) -> RedirectResponse:
    """Complete the Gmail OAuth flow, then redirect back to the app root.

    Gated the same as /start: a request reaching here without the feature
    enabled 403s rather than silently completing a login the operator can't
    use yet.

    Unlike a JSON API route, this one is a browser redirect target: there is
    nowhere for a JSON error page to be seen. Google's own denied-consent
    redirect (`?error=access_denied`, with no `code`/`state`) and a failed
    token exchange are therefore never raised as HTTP errors — both redirect
    back to the app root with a `gmailError` query param instead of the
    normal success redirect, so `code`/`state` are optional here. The same
    goes for the feature gate: closed mid-flow (key cleared or the toggle
    turned off while the consent screen was open), it redirects with
    `gmailError=not_enabled` rather than rendering a 403 JSON body.
    """
    try:
        require_gmail_tracking_enabled()
    except HTTPException:
        query = urlencode({"gmailError": "not_enabled"})
        return RedirectResponse(url=f"/?{query}")
    if error or not code or not state:
        query = urlencode({"gmailError": error or "missing_code"})
        return RedirectResponse(url=f"/?{query}")
    try:
        gmail_auth.complete_login(code, state)
    except gmail_auth.AuthError:
        query = urlencode({"gmailError": "auth_failed"})
        return RedirectResponse(url=f"/?{query}")
    return RedirectResponse(url="/")


@router.get("/gmail/status", response_model=GmailStatusModel)
def get_gmail_status() -> GmailStatusModel:
    """Gmail connection status for the Settings page.

    Unlike /auth/gmail/start and /callback, this route never 403s: it
    reports the useForEmailTracking gate's own state (tracking_enabled) so
    the UI can explain why Gmail is unavailable, rather than getting a
    blanket error.
    """
    jev_conn = secretstore.get_connection("jev")
    tracking_enabled = bool(jev_conn.get("apiKey")) and jev_conn.get("useForEmailTracking") is True
    oauth = secretstore.get_connection("gmail").get("oauth") or {}
    return GmailStatusModel(
        connected=bool(oauth.get("email")),
        email=oauth.get("email") or None,
        reauth_required=oauth.get("reauthRequired") is True,
        tracking_enabled=tracking_enabled,
    )


@router.post("/gmail/responses/sync")
def sync_gmail_responses(body: GmailSyncRequest | None = None) -> dict:
    """Trigger a Gmail response-tracking sync. Gated the same as the OAuth
    routes: requires a saved Jev key and useForEmailTracking enabled.

    Returns gmailsync.service.run_sync's own summary dict unchanged.
    """
    require_gmail_tracking_enabled()
    from gmailsync import service as gmailsync_service

    force = body.force if body is not None else False
    return gmailsync_service.run_sync(force=force)


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
    return AgentConfigModel.model_validate(
        agent_config_service.build_agent_config(include_feed)
    )


@router.put("/agent/config", response_model=AgentConfigModel)
def put_agent_config(body: AgentConfigUpdate) -> AgentConfigModel:
    """Merge only the fields the client sent onto the stored config.

    Profiles are WHOLESALE-REPLACED (not merged) because a null or omitted
    profiles field never reaches the merge dict. job_boards is replaced the
    same way, but first NORMALISED: the response-only keys (domain,
    effective_signin_url, is_default, is_api, key_required) are stripped — they are
    derived, and a stored copy is a second writer that can go stale — and a default-source
    entry is DROPPED only when it carries neither a signin_url NOR a disabled
    flag, so a client echoing back the resolved GET list does not bloat
    storage with the defaults. A default-source entry WITH a signin_url
    override or with ``enabled: false`` is kept, since both are legitimate
    per-board state that would otherwise have nowhere to live.

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
    data["job_boards"] = agent_config_service.resolved_job_boards(saved)
    return AgentConfigModel.model_validate(data)


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

    return AgentLlmCredentials.model_validate(
        agent_credentials_service.credentials_for_route(modelrouting.load().agent)
    )


@router.post("/agent/llm-token/refresh", response_model=AgentLlmTokenResult)
def post_agent_llm_token_refresh(
    body: AgentLlmTokenRefresh, x_agent_token: str = Header(default="")
) -> AgentLlmTokenResult:
    """Guarded (404 without AGENT_API_TOKEN): force a fresh subscription token
    after the caller saw `rejectedTokenSha256` rejected. 404 when the card has
    no oauth token or is in apikey mode; 503 when reconnecting is needed.
    The token is response-only and never logged."""
    if not _agent_token_ok(x_agent_token):
        raise HTTPException(status_code=404)
    token = agent_credentials_service.refresh_token(body.provider, body.rejected_token_sha256)
    return AgentLlmTokenResult(token=token)


@router.get("/agent/llm-routes")
def get_agent_llm_routes(x_agent_token: str = Header(default="")) -> dict:
    """Guarded (404 without AGENT_API_TOKEN): credentials for the apply route
    and each agent stage. A stage with no route resolves to null. Response-only
    egress; tokens are never logged."""
    if not _agent_token_ok(x_agent_token):
        raise HTTPException(status_code=404)
    return agent_credentials_service.stage_routes()


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


@router.get("/agent/status", response_model=AgentStatus)
def get_agent_status() -> AgentStatus:
    """Return the agent supervisor's running/idle state.

    Forwards to supervisor.js GET /status over the compose network.
    Returns 503 when the agent container is unreachable, 502 when it answers
    with an error (403 = AGENT_API_TOKEN mismatch).
    """
    data = supervisor_service.forward_to_supervisor("/status", method="GET")
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
    data = supervisor_service.forward_to_supervisor("/run", method="POST")
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
    data = supervisor_service.forward_to_supervisor("/cancel", method="POST")
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
    sites = [SigninQueueSite(**e) for e in screenings_service.signin_queue()]
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


@router.get("/settings", response_model=SettingsStatus)
def get_settings() -> SettingsStatus:
    return SettingsStatus(**settings_service.settings_status())


@router.post("/settings", response_model=SettingsStatus)
def post_settings(body: SettingsUpdate) -> SettingsStatus:
    """Old single-provider POST shape, shimmed onto the v2 store: the key/host
    lands in that provider's connection, and {connection, model} becomes the
    routing default."""
    status = settings_service.save_v1_settings(
        body.active_provider, body.api_key, body.ollama_host, body.model
    )
    return SettingsStatus(**status)


@router.post("/settings/test", response_model=TestResult)
def test_settings(body: SettingsUpdate) -> TestResult:
    ok, detail = settings_service.test_v1_settings(
        body.active_provider,
        body.api_key,
        body.ollama_host,
        body.model,
        provider_factory=lambda: get_provider(refresh=True),
    )
    return TestResult(ok=ok, detail=detail)


def _lazy_provider(module: str, cls: str):
    """Constructor that imports the provider SDK module only when called, so
    the model list keeps importing just the provider it was asked for."""

    def build(**kwargs):
        return getattr(importlib.import_module(module), cls)(**kwargs)

    return build


_V1_PROVIDER_BUILDERS = {
    "claude": _lazy_provider("providers.anthropic_provider", "AnthropicProvider"),
    "codex": _lazy_provider("providers.openai_provider", "OpenAIProvider"),
    "ollama": _lazy_provider("providers.ollama_provider", "OllamaProvider"),
}


@router.post("/models", response_model=ModelList)
def list_models(body: SettingsUpdate) -> ModelList:
    """Live model list for the selected provider, pulled from its API/SDK."""
    models, card = settings_service.list_v1_models(
        body.active_provider, body.api_key, body.ollama_host, _V1_PROVIDER_BUILDERS
    )
    return _models_result(models, card)


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


@router.post("/auth/{provider}/start", response_model=StartLoginResult)
def start_connection_login(provider: str) -> StartLoginResult:
    return StartLoginResult.model_validate(connections_service.start_login(provider))


# Specific route must come BEFORE the generic /{provider}/complete to avoid
# FastAPI matching /api/auth/claude/complete against the general pattern.
@router.post("/auth/claude/complete", response_model=ConnectionStatus)
def complete_claude_login_alias(body: CompleteLoginRequest) -> ConnectionStatus:
    """Deprecated: delegates to the generic /complete handler. Retained so a
    deployed web bundle from before this change does not break mid-deploy."""
    return _complete_login("claude", body)


@router.post("/auth/{provider}/complete", response_model=ConnectionStatus)
def _complete_login(provider: str, body: CompleteLoginRequest) -> ConnectionStatus:
    connections_service.complete_login(provider, body.code)
    return _connection_status(provider)


@router.post("/auth/{provider}/poll", response_model=PollLoginResult)
def _poll_login(provider: str) -> PollLoginResult:
    result = connections_service.poll_login(provider)
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


@router.post("/auth/{provider}/key", response_model=ModelList)
def post_connection_key(provider: str, body: ApiKeyRequest) -> ModelList:
    models = connections_service.save_key(provider, body.api_key, body.base_url, body.bearer)
    return _models_result(models, provider)


@router.get("/auth/{provider}/models", response_model=ModelList)
def get_connection_models(provider: str) -> ModelList:
    connections_service.require_card(provider)
    try:
        models = build_connection_provider(provider, None).list_models()
    except ProviderError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 — surface upstream LLM/SDK errors cleanly
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}") from e
    return _models_result(models, provider)


@router.post("/auth/{provider}/test", response_model=TestResult)
def test_connection(provider: str, body: ConnectionTestRequest) -> TestResult:
    connections_service.require_card(provider)
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
    connections_service.logout(provider, mode)
    return _connection_status(provider)


@router.get("/routing", response_model=RoutingModel)
def get_routing() -> RoutingModel:
    """Get the current model routing configuration."""
    return _routing_model(modelrouting.load())


@router.put("/routing", response_model=RoutingModel)
def put_routing(body: RoutingUpdate) -> RoutingModel:
    """Merge only the fields the client sent onto the stored routing.

    A field explicitly sent as null is not the same as an absent field: it
    clears that route (`default`/`agent` sent as null, or a `tasks` entry
    sent as null, removes it) instead of leaving the stored value untouched.
    """
    # Prepare update from body — exclude_unset only, so an explicit null
    # survives into update_dict and is distinguishable from an absent field.
    update_dict = body.model_dump(exclude_unset=True, by_alias=False)
    return _routing_model(settings_service.update_routing(update_dict))


def _routing_model(routing: modelrouting.Routing) -> RoutingModel:
    """Convert a stored Routing to its API wire model."""
    return RoutingModel(
        tasks={k: _route_model(v) for k, v in routing.tasks.items()},
        agent=_route_model(routing.agent) if routing.agent else None,
        default=_route_model(routing.default) if routing.default else None,
        agent_stages={k: _route_model(v) for k, v in routing.agent_stages.items()},
    )


def _route_model(route: modelrouting.Route) -> RouteModel:
    """Convert a stored Route to its API wire model."""
    return RouteModel(
        connection=route.connection,
        model=route.model,
        effort=route.effort,
    )
