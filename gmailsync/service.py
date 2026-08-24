from __future__ import annotations

import base64
import html
import re
import time
from email.utils import parseaddr

import httpx

from applications.store import load_all
from connections.auth.gmail import AuthError, get_valid_access_token
from providers import ProviderError, get_provider
from truth.answers import load as load_answers

from .matcher import match_message
from .model import GmailSuggestion, GmailSyncState
from .store import load_suggestions, load_sync_state, save_suggestions, save_sync_state

SYNC_THROTTLE_S = 3600


class GmailSyncError(RuntimeError):
    def __init__(self, message: str, *, reconnect_required: bool = False) -> None:
        super().__init__(message)
        self.reconnect_required = reconnect_required


class GmailClient:
    def __init__(self, access_token: str) -> None:
        self._headers = {"Authorization": f"Bearer {access_token}"}

    def _get(self, path: str, **params):
        try:
            resp = httpx.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/{path}",
                headers=self._headers,
                params=params,
                timeout=30,
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
        messages: list[dict] = []
        page_token = None
        while True:
            payload = self._get(
                "messages",
                q=query,
                maxResults=100,
                pageToken=page_token,
            )
            messages.extend(payload.get("messages") or [])
            page_token = payload.get("nextPageToken")
            if not page_token:
                return messages

    def get_metadata(self, message_id: str) -> dict:
        return self._get(
            f"messages/{message_id}",
            format="metadata",
            metadataHeaders=["From", "Subject", "Date", "To"],
        )

    def get_full(self, message_id: str) -> dict:
        return self._get(f"messages/{message_id}", format="full")


def build_gmail_client() -> GmailClient:
    try:
        return GmailClient(get_valid_access_token())
    except AuthError as exc:
        raise GmailSyncError(str(exc), reconnect_required=exc.reconnect_required) from exc


def _header(payload: dict, name: str) -> str:
    headers = payload.get("payload", {}).get("headers") or []
    target = name.lower()
    for header in headers:
        if str(header.get("name", "")).lower() == target:
            return str(header.get("value", ""))
    return ""


def _decode_body(part: dict) -> str:
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


def _classify_message(subject: str, snippet: str, body: str) -> tuple[str, str]:
    schema = {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["rejection", "interview", "offer", "confirmation", "other"],
            }
        },
        "required": ["classification"],
        "additionalProperties": False,
    }
    prompt = (
        "Classify this employer reply email for a job application. "
        "Return rejection, interview, offer, confirmation, or other."
    )
    messages = [
        {
            "role": "user",
            "content": f"Subject: {subject}\n\nSnippet: {snippet}\n\nBody:\n{body[:12000]}",
        }
    ]
    try:
        result = get_provider(task="gmail-sync").extract_json(prompt, messages, schema)
    except ProviderError:
        return "", ""
    classification = str(result.get("classification", "")).strip()
    suggested = {
        "rejection": "Rejected",
        "interview": "Interviewing",
        "offer": "Offer",
        "confirmation": "Waiting",
        "other": "Waiting",
    }.get(classification, "")
    return classification, suggested


def _query(last_synced_at: float, target_email: str) -> str:
    parts = [f'to:{target_email}']
    if last_synced_at > 0:
        parts.append(f"after:{int(last_synced_at)}")
    return " ".join(parts)


def _pending_candidates():
    return [app for app in load_all() if not app.response_received]


def _sender_email(value: str) -> str:
    return parseaddr(value)[1].strip().lower()


def _sorted_pending(items: list[GmailSuggestion]) -> list[GmailSuggestion]:
    return sorted((item for item in items if item.state == "pending"), key=lambda item: item.date, reverse=True)


def current_state() -> GmailSyncState:
    return load_sync_state()


def pending_suggestions() -> list[GmailSuggestion]:
    return _sorted_pending(load_suggestions())


def run_sync(*, force: bool = False) -> dict:
    sync_state = load_sync_state()
    now = time.time()
    if not force and sync_state.last_synced_at and now - sync_state.last_synced_at < SYNC_THROTTLE_S:
        return {
            "skipped": True,
            "last_synced_at": sync_state.last_synced_at,
            "processed": 0,
            "suggestions": len(_sorted_pending(load_suggestions())),
        }
    answers = load_answers()
    if not answers.email.strip():
        raise GmailSyncError("Set your email address in Answers before syncing Gmail.")
    client = build_gmail_client()
    existing = load_suggestions()
    by_id = {item.id: item for item in existing}
    processed_ids = set(sync_state.processed_message_ids)
    pending_apps = _pending_candidates()
    new_processed: list[str] = []
    query = _query(sync_state.last_synced_at, answers.email.strip())
    for item in client.list_messages(query):
        message_id = str(item.get("id", ""))
        if not message_id or message_id in processed_ids:
            continue
        metadata = client.get_metadata(message_id)
        sender = _header(metadata, "From")
        subject = _header(metadata, "Subject")
        date = _header(metadata, "Date")
        snippet = str(metadata.get("snippet", ""))
        match = match_message(pending_apps, sender=sender, subject=subject, snippet=snippet)
        if match is None:
            new_processed.append(message_id)
            continue
        full = client.get_full(message_id)
        body = _decode_body(full.get("payload") or {})
        classification, suggested_status = _classify_message(subject, snippet, body)
        if message_id not in by_id:
            by_id[message_id] = GmailSuggestion(
                id=message_id,
                application_id=match.application_id,
                application_label=match.application_label,
                sender=sender,
                sender_email=_sender_email(sender),
                subject=subject,
                date=date,
                snippet=snippet,
                classification=classification,
                suggested_status=suggested_status,
                match_confidence=match.confidence,
                match_evidence=match.evidence,
                state="pending",
            )
        new_processed.append(message_id)
    sync_state.last_synced_at = now
    sync_state.processed_message_ids = sorted(processed_ids.union(new_processed))
    save_suggestions(list(by_id.values()))
    save_sync_state(sync_state)
    return {
        "skipped": False,
        "last_synced_at": sync_state.last_synced_at,
        "processed": len(new_processed),
        "suggestions": len(_sorted_pending(list(by_id.values()))),
    }
