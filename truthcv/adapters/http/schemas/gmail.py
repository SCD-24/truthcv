"""Wire models for the Gmail integration."""

from __future__ import annotations

from pydantic import Field

from .common import _Camel


class GmailStatusModel(_Camel):
    """GET /api/gmail/status response.

    Reports the useForEmailTracking gate's own state instead of 403ing, so
    the Settings page can explain why Gmail is unavailable rather than
    getting a blanket error.
    """

    connected: bool = False
    email: str | None = None
    reauth_required: bool = False
    tracking_enabled: bool = False
    refresh_expires_at: float | None = None


class GmailSyncRequest(_Camel):
    """POST /api/gmail/responses/sync body."""

    force: bool = False


# Upper bound on suggestion ids accepted by one dismiss request.
MAX_DISMISS_IDS = 200


class GmailDismissRequest(_Camel):
    """POST /api/gmail/suggestions/dismiss body."""

    ids: list[str] = Field(min_length=1, max_length=MAX_DISMISS_IDS)
