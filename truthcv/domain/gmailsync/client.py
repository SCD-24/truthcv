"""Thin Gmail REST client and message-payload decoding."""
from __future__ import annotations

import base64
import html
import re

import httpx

#: Per-request timeout (seconds) for Gmail REST calls.
GMAIL_HTTP_TIMEOUT_S = 30

#: Page size requested from the Gmail messages.list endpoint.
GMAIL_PAGE_SIZE = 100


class GmailSyncError(RuntimeError):
    """Raised when a Gmail sync step fails; may signal that reconnecting is required."""

    def __init__(self, message: str, *, reconnect_required: bool = False) -> None:
        super().__init__(message)
        self.reconnect_required = reconnect_required


class GmailClient:
    """Minimal Gmail REST client authenticated with a bearer access token."""

    def __init__(self, access_token: str) -> None:
        self._headers = {"Authorization": f"Bearer {access_token}"}

    def _get(self, path: str, **params):
        """GET a Gmail API path and return decoded JSON, mapping failures to GmailSyncError."""
        try:
            resp = httpx.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/{path}",
                headers=self._headers,
                params=params,
                timeout=GMAIL_HTTP_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            raise GmailSyncError("Gmail sync failed — could not reach Gmail.") from exc
        if resp.status_code in (401, 403):
            raise GmailSyncError(
                "Gmail access was revoked or expired — reconnect Gmail in Settings.",
                reconnect_required=True,
            )
        if resp.status_code != 200:
            raise GmailSyncError(f"Gmail sync failed ({resp.status_code}).")
        return resp.json()

    def list_messages(self, query: str) -> list[dict]:
        """Return all message stubs matching a Gmail search query, following pagination."""
        messages: list[dict] = []
        page_token = None
        while True:
            payload = self._get(
                "messages",
                q=query,
                maxResults=GMAIL_PAGE_SIZE,
                pageToken=page_token,
            )
            messages.extend(payload.get("messages") or [])
            page_token = payload.get("nextPageToken")
            if not page_token:
                return messages

    def get_metadata(self, message_id: str) -> dict:
        """Fetch a message in metadata format (From, Subject, Date, To headers)."""
        return self._get(
            f"messages/{message_id}",
            format="metadata",
            metadataHeaders=["From", "Subject", "Date", "To"],
        )

    def get_full(self, message_id: str) -> dict:
        """Fetch a message in full format, including body parts."""
        return self._get(f"messages/{message_id}", format="full")


def _header(payload: dict, name: str) -> str:
    """Return a message header value by case-insensitive name, or '' if absent."""
    headers = payload.get("payload", {}).get("headers") or []
    target = name.lower()
    for header in headers:
        if str(header.get("name", "")).lower() == target:
            return str(header.get("value", ""))
    return ""


def _decode_body(part: dict) -> str:
    """Decode a message part's text body, recursing into child parts; HTML is stripped."""
    data = part.get("body", {}).get("data") or ""
    if data:
        try:
            raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="ignore")
            if part.get("mimeType") == "text/html":
                raw = re.sub(r"<[^>]+>", " ", raw)
                raw = html.unescape(raw)
            return raw
        except Exception:
            return ""
    out = []
    for child in part.get("parts") or []:
        text = _decode_body(child)
        if text:
            out.append(text)
    return "\n".join(out)
