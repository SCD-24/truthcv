"""HTTP guards shared by the Gmail route modules."""

from __future__ import annotations

from fastapi import HTTPException

from truthcv.services import gmail as gmail_service


def require_gmail_tracking_enabled() -> None:
    """Raise 403 unless Gmail response-tracking is configured and opted in.

    Exists so the Gmail route modules share one HTTP gate; the predicate itself
    lives in ``truthcv.services.gmail.tracking_enabled``.
    """
    if not gmail_service.tracking_enabled():
        raise HTTPException(
            status_code=403,
            detail="Gmail response-tracking requires a saved Jev API key and useForEmailTracking enabled.",
        )
