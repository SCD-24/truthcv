"""Wizard REST routes wired to the backend modules.

The one hard rule lives in /api/render: the guardrail runs BEFORE any file is
produced, and if it fails nothing is rendered — the response is blocked=true with
the unverifiable tokens.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

import tailor as tailor_engine
from guardrail import Scope, validate
from providers import ProviderError, get_provider
from render import lint, render_docx, render_html, render_pdf
from render.pdf import RenderUnavailable
from truth import load, persist_source_hash, save
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
from api import secrets as secrets_store

from .schemas import (
    ApplicationCreate,
    ApplicationDocument,
    ApplicationModel,
    ApplicationUpdate,
    AtsWarning,
    ConfirmInferencesRequest,
    CoverLetterApprovals,
    CoverLetterRequest,
    CoverLetterResult,
    ModelInfo,
    ModelList,
    BlockedClaimModel,
    ProfileStatus,
    RenderRequest,
    RenderResult,
    SaveCoverLetterRequest,
    SaveCvRequest,
    SaveDocumentResult,
    SettingsStatus,
    SettingsUpdate,
    TailorRequest,
    TailorResult,
    TestResult,
    TruthDoc,
)

router = APIRouter(prefix="/api")


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
        truth = build_truth_from_text(text, get_provider())
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
        result = tailor_engine.tailor(body.posting, load(), get_provider())
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


def _settings_status() -> SettingsStatus:
    creds = secrets_store.resolve_credentials()
    return SettingsStatus(
        encryption_available=secrets_store.encryption_available(),
        active_provider=creds["activeProvider"],
        model=creds["model"],
        anthropic_key_set=bool(creds["anthropicApiKey"]),
        openai_key_set=bool(creds["openaiApiKey"]),
        ollama_host=creds["ollamaHost"],
    )


@router.get("/profile", response_model=ProfileStatus)
def profile() -> ProfileStatus:
    return ProfileStatus(has_profile=has_profile())


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

    approved_texts, denied_texts, paragraphs = _letter_approvals(body.approvals)

    try:
        letter = build_letter(
            posting_file.read_text(encoding="utf-8"),
            body.tone,
            body.length,
            load(),
            get_provider(),
            approved_texts=approved_texts,
            denied_texts=denied_texts,
            paragraphs=paragraphs,
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
    if not secrets_store.encryption_available():
        raise HTTPException(status_code=400, detail="Set ENCRYPTION_KEY in .env first.")
    current = secrets_store.read_secrets()
    current["activeProvider"] = body.active_provider
    if body.model is not None:
        current["model"] = body.model
    if body.ollama_host:
        current["ollamaHost"] = body.ollama_host
    if body.api_key:  # empty/None leaves the stored key unchanged
        field = {"anthropic": "anthropicApiKey", "openai": "openaiApiKey"}.get(
            body.active_provider
        )
        if field:
            current[field] = body.api_key
    secrets_store.write_secrets(current)
    from providers import reset_provider

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

    Uses a key/host typed in the form if present, otherwise the saved credential
    — so the model list can load with an unsaved key (like Test connection) and
    without writing secrets just to populate a dropdown.
    """
    name = (body.active_provider or "").strip().lower()
    creds = secrets_store.resolve_credentials()
    if name == "anthropic":
        from providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=body.api_key or creds["anthropicApiKey"] or None)
    if name == "openai":
        from providers.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=body.api_key or creds["openaiApiKey"] or None)
    if name == "ollama":
        from providers.ollama_provider import OllamaProvider

        return OllamaProvider(host=body.ollama_host or creds["ollamaHost"] or None)
    raise HTTPException(status_code=400, detail=f"Unknown provider '{name}'.")


@router.post("/models", response_model=ModelList)
def list_models(body: SettingsUpdate) -> ModelList:
    """Live model list for the selected provider, pulled from its API/SDK."""
    try:
        provider = _provider_from_update(body)
        models = provider.list_models()
    except HTTPException:
        raise
    except ProviderError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}") from e
    return ModelList(
        models=[ModelInfo(id=m["id"], label=m.get("label") or m["id"]) for m in models]
    )
