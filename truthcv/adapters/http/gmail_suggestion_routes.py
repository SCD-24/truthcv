"""FastAPI routes for listing, accepting and dismissing pending Gmail suggestions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query

from truthcv.services import gmail as gmail_service

from .schemas import GmailDismissRequest

router = APIRouter(prefix="/api/gmail/suggestions")

# Default and maximum page size for the pending-suggestions listing.
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100
# Upper bound on a suggestion id path segment.
MAX_SUGGESTION_ID_LEN = 200


def _guard() -> None:
    """Reuse the exact gate the existing Gmail sync route enforces."""
    from truthcv.adapters.http.guards import require_gmail_tracking_enabled

    require_gmail_tracking_enabled()


@router.get("")
def list_suggestions(
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict:
    """One page of pending suggestions, newest first, plus the pending total."""
    _guard()
    from truthcv.domain.gmailsync import service as gmailsync_service

    items, total = gmailsync_service.list_pending(limit, offset)
    return {"items": [s.to_dict() for s in items], "total": total}


@router.post("/dismiss")
def dismiss_suggestions(body: GmailDismissRequest) -> dict:
    """Dismiss the given pending suggestions; report the count and remaining pending."""
    _guard()

    dismissed, pending = gmail_service.dismiss_and_count(body.ids)
    return {"dismissed": dismissed, "pending": pending}


@router.post("/{suggestion_id}/accept")
def accept_suggestion(
    suggestion_id: str = Path(..., min_length=1, max_length=MAX_SUGGESTION_ID_LEN),
) -> dict:
    """Apply one pending suggestion's status to its application; report it and remaining pending.

    404 for an unknown id; 409 when it is no longer pending, carries no status
    to apply, or its application no longer exists.
    """
    _guard()
    from truthcv.domain.gmailsync import service as gmailsync_service

    try:
        accepted, pending = gmail_service.accept_and_count(suggestion_id)
    except gmailsync_service.SuggestionNotFound:
        raise HTTPException(status_code=404, detail="Email response not found.") from None
    except gmailsync_service.SuggestionNotAcceptable:
        raise HTTPException(status_code=409, detail="This email response can no longer be accepted.") from None
    return {"suggestion": accepted.to_dict(), "pending": pending}
