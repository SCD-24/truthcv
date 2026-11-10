"""Wire-shaping helpers shared by more than one resource router."""

from __future__ import annotations

from truthcv.integrations.providers.base import supports_effort_levels

from .schemas import (
    ApplicationDocument,
    ApplicationModel,
    ModelInfo,
    ModelList,
)


def _download_url(name: str) -> str | None:
    """Download URL for a rendered file, or None if it isn't on the volume.

    Why check existence: a file may be recorded on the application but missing in
    an environment where WeasyPrint/pandoc wasn't available at save time.
    """
    if not name:
        return None
    from truthcv.infra.storage import data_dir

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
