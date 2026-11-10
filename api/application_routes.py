"""Application routes: the tracked-application list, export, edits and saved documents."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import services.applications as applications_service

import applications as app_store

from .route_support import _application_model
from .schemas import (
    ApplicationCreate,
    ApplicationListResponse,
    ApplicationModel,
    ApplicationUpdate,
    SaveCoverLetterRequest,
    SaveCvRequest,
    SaveDocumentResult,
)

router = APIRouter()


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
