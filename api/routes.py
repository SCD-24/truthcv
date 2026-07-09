"""Wizard REST routes wired to the backend modules.

The one hard rule lives in /api/render: the guardrail runs BEFORE any file is
produced, and if it fails nothing is rendered — the response is blocked=true with
the unverifiable tokens.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile

import tailor as tailor_engine
from guardrail import validate
from providers import ProviderError, get_provider
from render import lint, render_docx, render_html, render_pdf
from render.pdf import RenderUnavailable
from truth import load, save
from truth.extract import build_truth_from_text, write_confirmed
from truth.model import TruthEntry
from truth.pdf import (
    PdfExtractError,
    extract_text,
    has_profile,
    load_source_text,
    persist_profile,
    persist_source_text,
)

from api import secrets as secrets_store

from .schemas import (
    AtsWarning,
    ConfirmInferencesRequest,
    CoverLetterRequest,
    CoverLetterResult,
    EntriesResponse,
    JobFetchRequest,
    JobFetchResponse,
    ProfileStatus,
    PutTruthRequest,
    RenderResult,
    SettingsStatus,
    SettingsUpdate,
    TailorRequest,
    TailorResult,
    TestResult,
    TruthEntryModel,
)

router = APIRouter(prefix="/api")


def _entries_response(entries: list[TruthEntry]) -> EntriesResponse:
    return EntriesResponse(
        entries=[TruthEntryModel(**e.to_dict()) for e in entries]
    )


@router.post("/upload", status_code=204)
async def upload(file: UploadFile = File(...)) -> None:
    data = await file.read()
    try:
        text = extract_text(data)
    except PdfExtractError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    persist_source_text(text)
    persist_profile(data)


@router.post("/extract", response_model=EntriesResponse)
def extract() -> EntriesResponse:
    text = load_source_text()
    if not text.strip():
        raise HTTPException(status_code=400, detail="Upload a PDF before extracting.")
    try:
        entries = build_truth_from_text(text, get_provider())
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 — surface upstream LLM/SDK errors cleanly
        raise HTTPException(
            status_code=502,
            detail=f"The language model call failed: {type(e).__name__}: {e}",
        ) from e
    return _entries_response(entries)


@router.get("/truth", response_model=EntriesResponse)
def get_truth() -> EntriesResponse:
    return _entries_response(load())


@router.put("/truth", status_code=204)
def put_truth(body: PutTruthRequest) -> None:
    entries = [TruthEntry.from_dict(e.model_dump(by_alias=False)) for e in body.entries]
    try:
        save(entries)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/job/fetch", response_model=JobFetchResponse)
def job_fetch(body: JobFetchRequest) -> JobFetchResponse:
    """Best-effort: always 200. On any failure return empty text."""
    text = ""
    try:
        resp = httpx.get(body.url, timeout=8.0, follow_redirects=True)
        if resp.status_code == 200:
            import re

            stripped = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", resp.text, flags=re.I | re.S)
            text = re.sub(r"<[^>]+>", " ", stripped)
            text = re.sub(r"\s+", " ", text).strip()
    except Exception:  # noqa: BLE001
        text = ""
    return JobFetchResponse(text=text)


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
    claims = tailor_engine.claims_for_ids(body.approved_ids)
    write_confirmed(claims)


@router.post("/render", response_model=RenderResult)
def render_route() -> RenderResult:
    draft = tailor_engine.load_draft()
    if draft is None:
        raise HTTPException(status_code=400, detail="Tailor a posting before rendering.")

    truth_values = [e.value for e in load()]
    draft_texts = [line.text for line in draft.lines]

    # Guardrail FIRST — nothing renders unless it passes.
    result = validate(draft_texts, truth_values)
    if not result.ok:
        return RenderResult(blocked=True, unverifiable=result.unverifiable)

    lines = [line.to_dict() for line in draft.lines]
    html = render_html(lines)
    ats = [AtsWarning(**w) for w in lint(html, draft.keywords)]

    pdf_url = docx_url = None
    try:
        pdf_path = render_pdf(html)
        pdf_url = f"/api/download/{pdf_path.name}"
    except RenderUnavailable:
        pass
    try:
        docx_path = render_docx(html)
        docx_url = f"/api/download/{docx_path.name}"
    except RenderUnavailable:
        pass

    if pdf_url is None and docx_url is None:
        raise HTTPException(
            status_code=500,
            detail="Rendering backend unavailable (WeasyPrint/pandoc not installed).",
        )

    return RenderResult(
        blocked=False, ats_warnings=ats, pdf_url=pdf_url, docx_url=docx_url
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


@router.post("/cover-letter", response_model=CoverLetterResult)
def cover_letter(body: CoverLetterRequest) -> CoverLetterResult:
    from truth.store import data_dir

    posting_file = data_dir() / "posting.txt"
    if not posting_file.exists():
        raise HTTPException(
            status_code=400, detail="Tailor a posting before generating a cover letter."
        )

    from coverletter import build_letter
    from render.cover_letter import render_letter_html

    try:
        letter = build_letter(
            posting_file.read_text(encoding="utf-8"),
            body.tone,
            body.length,
            load(),
            get_provider(),
        )
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"The language model call failed: {type(e).__name__}: {e}",
        ) from e

    if letter["blocked"]:
        return CoverLetterResult(blocked=True, unverifiable=letter["unverifiable"])

    html = render_letter_html(letter["text"])
    pdf_url = docx_url = None
    try:
        pdf_url = f"/api/download/{render_pdf(html, 'cover_letter.pdf').name}"
    except RenderUnavailable:
        pass
    try:
        docx_url = f"/api/download/{render_docx(html, 'cover_letter.docx').name}"
    except RenderUnavailable:
        pass
    if pdf_url is None and docx_url is None:
        raise HTTPException(
            status_code=500,
            detail="Rendering backend unavailable (WeasyPrint/pandoc not installed).",
        )
    return CoverLetterResult(blocked=False, pdf_url=pdf_url, docx_url=docx_url)


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
