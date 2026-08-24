"""Wizard REST routes wired to the backend modules.

The one hard rule lives in /api/render: the guardrail runs BEFORE any file is
produced, and if it fails nothing is rendered — the response is blocked=true with
the unverifiable tokens.
"""

from __future__ import annotations

import hmac
import json
import os
import urllib.error
import urllib.request

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

import tailor as tailor_engine
from guardrail import Scope, validate
from providers import ProviderError, get_provider
from render import lint, render_docx, render_html, render_pdf
from render.pdf import RenderUnavailable
from truth import load, persist_source_hash, save
from truth.answers import Answers
from truth.answers import load as load_answers
from truth.answers import save as save_answers
from truth.extract import build_truth_from_text, write_confirmed
from truth.model import Truth
from truth.pdf import (
    PdfExtractError,
    extract_text,
    has_profile,
    load_source_text,
    persist_profile,
    persist_source_text,
)

import applications as app_store
import modelrouting
import secretstore
from agentconfig import store as agent_config_store
from connections import catalog
from connections.auth.claude import AuthError, get_valid_access_token
from connections.auth import claude as claude_auth
from providers import (
    ANTHROPIC_COMPAT_OPENROUTER_BASE_URL,
    OPENROUTER_BASE_URL,
    build_connection_provider,
    reset_provider,
)
from providers.base import supports_effort_levels
from companyboards import store as companyboards_store
from screening import store as screening_store
from screening.cooldown import cooldown as check_cooldown
from screening.model import Screening

import coverletter.store as letter_store
from agenttools.tools_letter import generate_cover_letter as _generate_letter

from .schemas import (
    AgentConfigModel,
    ApprovalUpdate,
    BulkApprovalResult,
    BulkApprovalUpdate,
    CompanyApprovalUpdate,
    CompanyBoardModel,
    CoverLetterDraftModel,
    LetterGenerateRequest,
    LetterSaveRequest,
    AgentConfigUpdate,
    AgentLlmCredentials,
    AgentRunResult,
    AgentStatus,
    AnswersModel,
    AnswersUpdate,
    ApiKeyRequest,
    ApplicationCreate,
    ApplicationDocument,
    ApplicationModel,
    ApplicationUpdate,
    AtsWarning,
    CompleteLoginRequest,
    ConfirmInferencesRequest,
    ConnectionList,
    ConnectionStatus,
    ConnectionTestRequest,
    CoverLetterApprovals,
    CoverLetterRequest,
    CooldownResult,
    CoverLetterResult,
    ModelInfo,
    ModelList,
    BlockedClaimModel,
    ProfileStatus,
    RenderRequest,
    RenderResult,
    RouteModel,
    RoutingModel,
    RoutingUpdate,
    SaveCoverLetterRequest,
    SaveCvRequest,
    SaveDocumentResult,
    ScreeningCreate,
    ScreeningModel,
    SettingsStatus,
    SettingsUpdate,
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


@router.post("/screenings", response_model=ScreeningModel, status_code=201)
def create_screening(body: ScreeningCreate) -> ScreeningModel:
    """Create a new screening record from client-supplied fields."""
    screening = screening_store.create(body.model_dump(by_alias=False))
    return _screening_model(screening)


def _has_draft(screening_id: str) -> bool:
    """Whether a letter exists to apply with.

    Approval licenses the agent to submit on the operator's behalf using the
    stored text verbatim. Approving with no text queues an application with
    nothing to send, so the check lives here rather than only in the UI.
    """
    draft = letter_store.load(screening_id)
    return draft is not None and bool(draft.text.strip())


# Declared BEFORE /screenings/{screening_id}: otherwise the router binds
# "approvals" as an id and this route is unreachable.
@router.patch("/screenings/approvals", response_model=BulkApprovalResult)
def bulk_set_approval(body: BulkApprovalUpdate) -> BulkApprovalResult:
    """Apply one approval decision to many screenings.

    Reports per-id outcomes rather than failing wholesale, so a partial failure
    is visible instead of silently dropping some ids. A draftless id is
    reported the same way rather than approved out from under the gate below.
    """
    try:
        results = []
        for sid in body.ids:
            if body.approval == "approved" and not _has_draft(sid):
                results.append({"id": sid, "ok": False})
                continue
            results.append(
                {"id": sid, "ok": screening_store.set_approval(sid, body.approval) is not None}
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return BulkApprovalResult(results=results)


@router.patch("/screenings/{screening_id}", response_model=ScreeningModel)
def set_screening_approval(screening_id: str, body: ApprovalUpdate) -> ScreeningModel:
    """The operator's approval decision and/or posting URL for one screening."""
    if body.approval is None and body.url is None:
        raise HTTPException(status_code=422, detail="Provide approval or url.")

    screening = None
    if body.url is not None:
        screening = screening_store.update(screening_id, {"url": body.url})
        if screening is None:
            raise HTTPException(status_code=404, detail="Screening not found.")

    if body.approval is not None:
        # Existence wins over the draft gate: an unknown id is 404 regardless
        # of approval value, matching the url-only branch above.
        if (
            body.approval == "approved"
            and screening_store.get(screening_id) is not None
            and not _has_draft(screening_id)
        ):
            raise HTTPException(
                status_code=409,
                detail="Draft a cover letter before approving — the agent applies with it verbatim.",
            )
        try:
            screening = screening_store.set_approval(screening_id, body.approval)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        if screening is None:
            raise HTTPException(status_code=404, detail="Screening not found.")

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
    result = _generate_letter(
        posting=screening.posting_text,
        tone=body.tone,
        length=body.length,
        company=screening.company or None,
    )
    if result["blocked"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The letter was blocked by the truthfulness guardrail.",
                "blockedReason": result.get("blocked_reason", ""),
                "blockedClaims": result["blocked_claims"],
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
    existing = letter_store.load(screening_id)
    draft = letter_store.CoverLetterDraft(
        text=body.text,
        paragraphs=existing.paragraphs if existing else [],
        source="operator",
    )
    return _draft_model(letter_store.save(screening_id, draft))


@router.patch("/company-boards/{company}", response_model=CompanyBoardModel)
def set_company_approval(company: str, body: CompanyApprovalUpdate) -> CompanyBoardModel:
    """Grant or revoke company-level trust.

    Weaker than approving a posting: it clears the blockers that caused a
    deferral, and never skips per-role screening. Recording the decision does
    not require a resolved careers board — most queued companies were screened
    from a posting URL and have none.
    """
    entry = companyboards_store.set_approved(company, body.approved)
    return CompanyBoardModel(
        company=entry.company,
        careers_url=entry.careers_url,
        ats=entry.ats,
        status=entry.status,
        approved=entry.approved,
    )


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
    return CooldownResult(in_cooldown=status.in_cooldown, expires=status.expires, blocked=status.blocked)


def _truth_doc(truth: Truth) -> TruthDoc:
    return TruthDoc.model_validate(truth.to_dict())


@router.post("/upload", status_code=204)
async def upload(file: UploadFile = File(...)) -> None:
    data = await file.read()
    try:
        text = extract_text(data)
    except PdfExtractError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    persist_source_text(text)
    persist_source_hash(text)  # keyed cache: lets /extract skip a repeat LLM pass
    persist_profile(data)


@router.post("/extract", response_model=TruthDoc)
def extract() -> TruthDoc:
    text = load_source_text()
    if not text.strip():
        raise HTTPException(status_code=400, detail="Upload a PDF before extracting.")
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
    from truth.store import data_dir

    (data_dir() / "posting.txt").write_text(body.posting, encoding="utf-8")
    return TailorResult.model_validate(
        {"keywords": result["keywords"], "inferences": result["inferences"]}
    )


@router.post("/confirm-inferences", status_code=204)
def confirm_inferences(body: ConfirmInferencesRequest) -> None:
    # Prefer the user-edited claims: the Confirm step lets the user reword an
    # inferred claim (and re-target its experience) before it becomes a fact, so
    # what they typed is what we persist. Fall back to the deprecated
    # approved_ids path, which writes each id's original draft claim.
    if body.approved:
        # A re-targeted experienceId the client made up (not in the draft) is
        # dropped to "" so write_confirmed attaches it to a safe default rather
        # than trusting an id that points nowhere.
        known = tailor_engine.valid_experience_ids()
        claims = [
            (a.experience_id if a.experience_id in known else "", a.claim)
            for a in body.approved
        ]
    else:
        claims = tailor_engine.claims_for_ids(body.approved_ids)
    write_confirmed(claims)


def _claim_id(scope_id: str, text: str) -> str:
    """Deterministic id for a blocked claim so the UI can round-trip decisions."""
    import hashlib

    return hashlib.sha256(f"{scope_id}\n{text}".encode("utf-8")).hexdigest()[:16]


def _contact_line(profile) -> str:
    """Compose the header's single contact line from identity fields.

    Identity is guardrail-exempt, so this is presentation only: email, phone,
    location and any link urls, joined with a middot, skipping blanks.
    """
    parts = [profile.email, profile.phone, profile.location]
    parts += [link.url for link in profile.links if link.url]
    return " · ".join(p for p in parts if p)


def _render_scopes(draft, truth) -> list[Scope]:
    """One guardrail scope per draft block, keyed by its truth source id."""
    exp_by_id = {e.id: e for e in truth.experiences}
    edu_by_id = {e.id: e for e in truth.education}
    scopes: list[Scope] = []
    for de in draft.experiences:
        te = exp_by_id.get(de.source_id)
        allowed = (
            [te.role, te.company, te.start, te.end] + [b.value for b in te.bullets]
            if te else []
        )
        scopes.append(
            Scope(id=de.source_id, texts=[de.role, de.company, de.dates, *de.bullets], allowed=allowed)
        )
    for de in draft.education:
        te = edu_by_id.get(de.source_id)
        allowed = [te.degree, te.school, te.start, te.end] if te else []
        scopes.append(Scope(id=de.source_id, texts=[de.degree, de.school, de.dates], allowed=allowed))
    scopes.append(Scope(id="skills", texts=list(draft.skills), allowed=[s.value for s in truth.skills]))
    # The profile summary is a claim: validate it (in its own scope) against
    # every truth fact it may legitimately draw on — role/company/dates/bullets
    # across all experiences and education. Identity fields (name/contact/links)
    # are exempt and never enter a scope. Skills flow in via global_values.
    summary = truth.profile.summary.strip()
    if summary:
        allowed_summary: list[str] = []
        for te in truth.experiences:
            allowed_summary += [te.role, te.company, te.start, te.end]
            allowed_summary += [b.value for b in te.bullets]
        for te in truth.education:
            allowed_summary += [te.degree, te.school, te.start, te.end]
        scopes.append(Scope(id="summary", texts=[summary], allowed=allowed_summary))
    return scopes


def _apply_approvals(scopes: list[Scope], approved: set[str], denied: set[str]) -> None:
    """Render-scoped only: approve => allow the claim's text here (NO truth
    write); deny => remove it from the draft texts so it can't ship."""
    for scope in scopes:
        kept: list[str] = []
        for text in scope.texts:
            cid = _claim_id(scope.id, text)
            if cid in denied:
                continue  # dropped from this render entirely
            if cid in approved:
                scope.allowed.append(text)  # traceable for THIS render only
            kept.append(text)
        scope.texts = kept


def _filter_denied_draft(draft, denied: set[str]):
    """Rebuild the draft without denied claims so the rendered CV omits them."""
    from copy import deepcopy

    out = deepcopy(draft)
    for de in out.experiences:
        de.bullets = [b for b in de.bullets if _claim_id(de.source_id, b) not in denied]
    out.skills = [s for s in out.skills if _claim_id("skills", s) not in denied]
    return out


@router.post("/render", response_model=RenderResult)
def render_route(body: RenderRequest | None = None) -> RenderResult:
    draft = tailor_engine.load_draft()
    if draft is None:
        raise HTTPException(status_code=400, detail="Tailor a posting before rendering.")

    truth = load()
    skill_values = [s.value for s in truth.skills]

    approved: set[str] = set()
    denied: set[str] = set()
    if body and body.approvals:
        approved = set(body.approvals.approved_claim_ids)
        denied = set(body.approvals.denied_claim_ids)

    scopes = _render_scopes(draft, truth)
    _apply_approvals(scopes, approved, denied)

    # Guardrail FIRST — nothing renders unless it passes.
    result = validate(scopes, global_values=skill_values)
    if not result.ok:
        # Return whole flagged claims (bullets), each with a stable id, so the
        # download step can offer per-claim approve/deny instead of dead-ending.
        blocked = [
            BlockedClaimModel(
                claim_id=_claim_id(c.scope_id, c.text),
                experience_id=c.scope_id,
                text=c.text,
                tokens=c.tokens,
            )
            for c in result.blocked_claims
        ]
        return RenderResult(blocked=True, unverifiable=result.unverifiable, blocked_claims=blocked)

    draft = _filter_denied_draft(draft, denied)
    html = render_html(
        draft,
        name=truth.profile.name or "Your Name",
        contact=_contact_line(truth.profile),
        summary=truth.profile.summary,
        email=truth.profile.email,
        phone=truth.profile.phone,
        location=truth.profile.location,
        links=[{"label": link.label, "url": link.url} for link in truth.profile.links],
    )
    ats = [AtsWarning(**w) for w in lint(html, draft.keywords)]

    # Attach to an application when asked: render to that application's own files
    # (retained + traceable) and persist the CV document; otherwise use the
    # shared scratch filenames (today's preview behavior).
    app_id = body.application_id if body else None
    if app_id and app_store.get(app_id) is not None:
        pdf_name, docx_name = app_store.cv_filenames(app_id)
    else:
        app_id = None
        pdf_name, docx_name = "cv.pdf", "cv.docx"

    # When attaching to an application, record the CV FIRST so the link always
    # persists; then render best-effort.
    if app_id:
        app_store.save_cv_document(app_id, html)

    pdf_url = docx_url = None
    try:
        pdf_path = render_pdf(html, pdf_name)
        pdf_url = f"/api/download/{pdf_path.name}"
    except RenderUnavailable:
        pass
    try:
        docx_path = render_docx(html, docx_name)
        docx_url = f"/api/download/{docx_path.name}"
    except RenderUnavailable:
        pass

    # A pure wizard preview (no application) has no saved document to fall back
    # on, so an unavailable backend is still a hard error there. An attached
    # render keeps its saved link even when nothing could be produced.
    if pdf_url is None and docx_url is None and not app_id:
        raise HTTPException(
            status_code=500,
            detail="Rendering backend unavailable (WeasyPrint/pandoc not installed).",
        )

    return RenderResult(
        blocked=False,
        ats_warnings=ats,
        pdf_url=pdf_url,
        docx_url=docx_url,
        html=html,
        # Attached save that produced no file: the CV source is recorded but its
        # links are null, so tell the UI rather than silently show no download.
        render_unavailable=bool(app_id) and pdf_url is None and docx_url is None,
    )


def _download_url(name: str) -> str | None:
    """Download URL for a rendered file, or None if it isn't on the volume.

    Why check existence: a file may be recorded on the application but missing in
    an environment where WeasyPrint/pandoc wasn't available at save time.
    """
    if not name:
        return None
    from truth.store import data_dir

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
        **data,
    )


@router.get("/applications", response_model=list[ApplicationModel])
def list_applications() -> list[ApplicationModel]:
    """Every tracked job application, most recent first."""
    apps = sorted(app_store.load_all(), key=lambda a: a.created_at, reverse=True)
    return [_application_model(a) for a in apps]


_EXPORT_COLUMNS = (
    "company",
    "application_date",
    "website",
    "application_url",
    "submitted",
    "submission_type",
    "reached_out",
    "to_who",
    "response_received",
    "method",
    "notes",
    "posting",
    "documents",
)


def _app_document_files(app) -> list[str]:
    """Names of this application's rendered files that exist on the volume."""
    from truth.store import data_dir

    names = [*app_store.cv_filenames(app.id), *app_store.cover_letter_filenames(app.id)]
    return [n for n in names if (data_dir() / n).exists()]


def _app_csv_row(app) -> list[str]:
    """One CSV row: editable fields plus a summary of attached document files."""
    docs = "; ".join(_app_document_files(app))
    values = {f: getattr(app, f) for f in app.EDITABLE}
    values["documents"] = docs
    return [str(values.get(col, "")) for col in _EXPORT_COLUMNS]


def _safe_folder(name: str, fallback: str, used: set[str]) -> str:
    """A filesystem-safe, unique folder name for a company (fallback if empty)."""
    import re

    base = re.sub(r'[<>:"/\\|?*]+', "_", (name or "").strip()) or fallback
    candidate, n = base, 2
    while candidate in used:
        candidate, n = f"{base} ({n})", n + 1
    used.add(candidate)
    return candidate


def _write_csv(zf, apps) -> None:
    """Write applications.csv (header + one row per application) into the zip."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_EXPORT_COLUMNS)
    for app in apps:
        writer.writerow(_app_csv_row(app))
    zf.writestr("applications.csv", buffer.getvalue())


def _write_documents(zf, apps) -> None:
    """Add each application's existing files under a per-company folder."""
    from truth.store import data_dir

    used: set[str] = set()
    for app in apps:
        files = _app_document_files(app)
        if not files:
            continue
        folder = _safe_folder(app.company, app.id, used)
        for name in files:
            zf.write(str(data_dir() / name), arcname=f"{folder}/{name}")


def _build_export_zip(apps):
    """Build the export zip in memory and return a rewound BytesIO stream."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_csv(zf, apps)
        _write_documents(zf, apps)
    buffer.seek(0)
    return buffer


@router.get("/applications/export")
def export_applications() -> StreamingResponse:
    """Download every application as a CSV plus per-company document folders.

    Bundled as one zip so a user gets an offline, portable record of the whole
    tracker: the table as `applications.csv`, and each application's rendered
    files grouped under a folder named for its company.
    """
    apps = sorted(app_store.load_all(), key=lambda a: a.created_at, reverse=True)
    archive = _build_export_zip(apps)
    headers = {"Content-Disposition": 'attachment; filename="applications.zip"'}
    return StreamingResponse(archive, media_type="application/zip", headers=headers)


@router.post("/applications", response_model=ApplicationModel, status_code=201)
def create_application(body: ApplicationCreate) -> ApplicationModel:
    """Create a new application record from client-supplied fields."""
    app = app_store.create(body.model_dump(by_alias=False))
    return _application_model(app)


@router.put("/applications/{app_id}", response_model=ApplicationModel)
def update_application(app_id: str, body: ApplicationUpdate) -> ApplicationModel:
    """Patch an application's editable fields (None fields are left unchanged)."""
    patch = body.model_dump(by_alias=False, exclude_none=True)
    app = app_store.update(app_id, patch)
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
        openai_key_set=bool(secretstore.get_connection("codex").get("apiKey")),
        ollama_host=secretstore.get_connection("ollama").get("baseUrl", ""),
    )


@router.get("/profile", response_model=ProfileStatus)
def profile() -> ProfileStatus:
    return ProfileStatus(has_profile=has_profile())


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


@router.get("/agent/config", response_model=AgentConfigModel)
def get_agent_config() -> AgentConfigModel:
    """Fetch agent config with resolved company boards.
    
    Prunes board entries for companies no longer on the target watchlist.
    """
    from companyboards import store as board_store
    
    cfg = agent_config_store.load()
    data = cfg.to_dict()
    
    # Load company boards and prune to target watchlist
    boards = board_store.load()
    board_store.prune(cfg.target_companies)
    
    # Populate company_boards in response
    data["company_boards"] = [
        {"company": board.company, "careers_url": board.careers_url, "ats": board.ats, "status": board.status, "resolved_at": board.resolved_at}
        for board in boards.values()
        if board.company.strip().casefold() in {name.strip().casefold() for name in cfg.target_companies}
    ]
    
    return AgentConfigModel.model_validate(data)


@router.put("/agent/config", response_model=AgentConfigModel)
def put_agent_config(body: AgentConfigUpdate) -> AgentConfigModel:
    """Merge only the fields the client sent onto the stored config.
    
    Profiles are WHOLESALE-REPLACED (not merged) because exclude_none=True
    means an omitted or null profiles field never reaches the merge dict.
    Other sibling fields (enabled, blocklist, schedule, globals) merge partially.
    """
    merged = agent_config_store.load().to_dict()
    merged.update(body.model_dump(exclude_unset=True, exclude_none=True, by_alias=False))
    cfg = agent_config_store.AgentConfig.from_dict(merged)
    return AgentConfigModel.model_validate(agent_config_store.save(cfg).to_dict())


@router.get("/agent/llm-credentials", response_model=AgentLlmCredentials)
def get_agent_llm_credentials(x_agent_token: str = Header(default="")) -> AgentLlmCredentials:
    """Guarded: only the unattended agent (holding AGENT_API_TOKEN) may call this.

    Returns 404 rather than 401/403 so the response carries no authentication hint.
    """
    secret = os.environ.get("AGENT_API_TOKEN", "").strip()
    given = x_agent_token.encode("utf-8", "surrogateescape")
    if not secret or not hmac.compare_digest(given, secret.encode("utf-8")):
        raise HTTPException(status_code=404)

    route = modelrouting.load().agent
    card = route.connection if route else "claude"
    model = route.model if route else ""

    # The agent IS the `claude` CLI, which speaks the Anthropic Messages API
    # and nothing else. OpenRouter serves that API too, so the CLI can be
    # pointed at it with ANTHROPIC_BASE_URL. Cards that only offer an
    # OpenAI-shaped surface (codex, ollama) have no path here.
    if card == "openrouter":
        api_key = secretstore.get_connection("openrouter").get("apiKey")
        if not api_key:
            raise HTTPException(status_code=404)
        return AgentLlmCredentials(
            auth_type="api_key",
            token=api_key,
            model=model,
            base_url=ANTHROPIC_COMPAT_OPENROUTER_BASE_URL,
        )
    if card != "claude":
        raise HTTPException(
            status_code=409,
            detail=f"Agent cannot run on the '{card}' connection: it does not "
            "serve the Anthropic Messages API the claude CLI requires.",
        )

    conn = secretstore.get_connection("claude")
    oauth = conn.get("oauth") or {}
    if oauth.get("accessToken") and conn.get("authMode") != "apikey":
        try:
            token = get_valid_access_token()
        except AuthError:
            raise HTTPException(
                status_code=503, detail="Claude subscription needs reconnecting."
            ) from None
        return AgentLlmCredentials(auth_type="oauth", token=token, model=model)

    api_key = conn.get("apiKey")
    if api_key:
        return AgentLlmCredentials(auth_type="api_key", token=api_key, model=model)

    raise HTTPException(status_code=404)


def _agent_control_url(path: str) -> str:
    """Build the supervisor.js control URL from env, defaulting port 9099."""
    port = os.environ.get("AGENT_CONTROL_PORT", "9099")
    return f"http://agent:{port}{path}"


def _forward_to_supervisor(path: str, method: str = "GET") -> dict:
    """Forward a request to the agent supervisor.js control server.

    Raises HTTPException(503) when the agent is unreachable.
    """
    token = os.environ.get("AGENT_API_TOKEN", "")
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
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=503, detail="Agent service unreachable") from exc


@router.get("/agent/status", response_model=AgentStatus)
def get_agent_status() -> AgentStatus:
    """Return the agent supervisor's running/idle state.

    Forwards to supervisor.js GET /status over the compose network.
    Returns 503 when the agent container is unreachable.
    """
    data = _forward_to_supervisor("/status", method="GET")
    return AgentStatus(
        running=data.get("running", False),
        last_started_at=data.get("lastStartedAt"),
        last_finished_at=data.get("lastFinishedAt"),
        last_exit_code=data.get("lastExitCode"),
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


def _letter_approvals(
    approvals: CoverLetterApprovals | None,
) -> tuple[set[str], set[str], list[dict] | None]:
    """Resolve blocked-claim ids to claim texts against the CACHED letter draft.

    Mirrors /api/render: ids are recomputed from the persisted paragraphs (same
    LETTER_SCOPE_ID + _claim_id hash), so a decision the UI made on a blocked
    attempt re-validates the exact letter the user saw. Returns
    (approved_texts, denied_texts, paragraphs); paragraphs is None on a first
    generate so build_letter produces and caches a fresh letter.
    """
    if not approvals or not (approvals.approved_claim_ids or approvals.denied_claim_ids):
        return set(), set(), None

    from coverletter import LETTER_SCOPE_ID, load_letter_draft

    paragraphs = load_letter_draft()
    if paragraphs is None:
        return set(), set(), None

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
    return approved, denied, paragraphs


@router.post("/cover-letter", response_model=CoverLetterResult)
def cover_letter(body: CoverLetterRequest) -> CoverLetterResult:
    from truth.store import data_dir

    posting_file = data_dir() / "posting.txt"
    if not posting_file.exists():
        raise HTTPException(
            status_code=400, detail="Tailor a posting before generating a cover letter."
        )

    from coverletter import build_letter, load_letter_draft
    from render.cover_letter import render_letter_html
    from truth.answers import load as load_answers

    approved_texts, denied_texts, paragraphs = _letter_approvals(body.approvals)

    # The profile answers (Agents page) are handed to the writer as allowed
    # claim sources for this generation only, never written to truth.
    answers = load_answers()
    try:
        letter = build_letter(
            posting_file.read_text(encoding="utf-8"),
            body.tone,
            body.length,
            load(),
            get_provider("cover_letter"),
            approved_texts=approved_texts,
            denied_texts=denied_texts,
            paragraphs=paragraphs,
            answers=answers,
        )
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"The language model call failed: {type(e).__name__}: {e}",
        ) from e

    if letter["blocked"]:
        blocked_claims = [
            BlockedClaimModel(
                claim_id=_claim_id(c.scope_id, c.text),
                experience_id=c.scope_id,
                text=c.text,
                tokens=c.tokens,
            )
            for c in letter["blocked_claims"]
        ]
        return CoverLetterResult(
            blocked=True,
            unverifiable=letter["unverifiable"],
            blocked_claims=blocked_claims,
        )

    _profile = load().profile
    html = render_letter_html(
        letter["text"],
        name=_profile.name or "Your Name",
        contact=_contact_line(_profile),
    )

    # Attach to an application when asked (per-application files + persisted
    # document); otherwise render to the shared scratch filenames.
    app_id = body.application_id if body.application_id else None
    if app_id and app_store.get(app_id) is not None:
        pdf_name, docx_name = app_store.cover_letter_filenames(app_id)
    else:
        app_id = None
        pdf_name, docx_name = "cover_letter.pdf", "cover_letter.docx"

    # Record the cover letter FIRST when attaching, so its link always
    # persists; then render best-effort.
    if app_id:
        app_store.save_cover_letter_document(app_id, letter["text"])

    pdf_url = docx_url = None
    try:
        pdf_url = f"/api/download/{render_pdf(html, pdf_name).name}"
    except RenderUnavailable:
        pass
    try:
        docx_url = f"/api/download/{render_docx(html, docx_name).name}"
    except RenderUnavailable:
        pass
    # Only a pure preview (no application) hard-errors on an unavailable backend;
    # an attached save keeps its recorded link.
    if pdf_url is None and docx_url is None and not app_id:
        raise HTTPException(
            status_code=500,
            detail="Rendering backend unavailable (WeasyPrint/pandoc not installed).",
        )
    return CoverLetterResult(
        blocked=False,
        pdf_url=pdf_url,
        docx_url=docx_url,
        text=letter["text"],
        render_unavailable=bool(app_id) and pdf_url is None and docx_url is None,
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


@router.post("/auth/{provider}/start", response_model=StartLoginResult)
def start_connection_login(provider: str) -> StartLoginResult:
    _require_card(provider)
    if provider != "claude":
        raise HTTPException(
            status_code=400,
            detail="Subscription sign-in is not available for this provider yet.",
        )
    return StartLoginResult.model_validate(claude_auth.start_login())


@router.post("/auth/claude/complete", response_model=ConnectionStatus)
def complete_connection_login(body: CompleteLoginRequest) -> ConnectionStatus:
    try:
        claude_auth.complete_login(body.code)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    reset_provider()
    return _connection_status("claude")


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
    _require_card(provider)
    secretstore.clear_mode(provider, mode or "apikey")
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
    return RouteModel(connection=route.connection, model=route.model, effort=route.effort)
