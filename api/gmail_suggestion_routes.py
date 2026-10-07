"""FastAPI routes for listing and dismissing pending Gmail suggestions."""

from __future__ import annotations

from fastapi import APIRouter, Query

from .schemas import GmailDismissRequest

router = APIRouter(prefix="/api/gmail/suggestions")

# Default and maximum page size for the pending-suggestions listing.
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100


def _guard() -> None:
    """Reuse the exact gate the existing Gmail sync route enforces."""
    from api.routes import require_gmail_tracking_enabled

    require_gmail_tracking_enabled()


@router.get("")
def list_suggestions(
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict:
    """One page of pending suggestions, newest first, plus the pending total."""
    _guard()
    from gmailsync import service as gmailsync_service

    items, total = gmailsync_service.list_pending(limit, offset)
    return {"items": [s.to_dict() for s in items], "total": total}


@router.post("/dismiss")
def dismiss_suggestions(body: GmailDismissRequest) -> dict:
    """Dismiss the given pending suggestions; report the count and remaining pending."""
    _guard()
    from gmailsync import service as gmailsync_service

    dismissed = gmailsync_service.dismiss(body.ids)
    _, pending = gmailsync_service.list_pending(1, 0)
    return {"dismissed": dismissed, "pending": pending}
