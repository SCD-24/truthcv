from __future__ import annotations

import base64
import html
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from email.utils import parseaddr

import httpx

from applications.store import get as get_application, load_all, update as update_application
from connections.auth.gmail import AuthError, get_valid_access_token
from screening import jev

from .matcher import _app_domains, _normalize, match_message
from .model import GmailSuggestion, GmailSyncState
from .store import load_suggestions, load_sync_state, save_suggestions, save_sync_state

logger = logging.getLogger(__name__)

SYNC_THROTTLE_S = 300

#: Bounded worker count for concurrent Gmail API fetches — both the per-
#: application list_messages queries in _collect_message_ids and the
#: per-message get_metadata prefetch in run_sync share this same pool size,
#: so a sync run never opens more than this many concurrent Gmail requests
#: regardless of how many applications or new messages there are.
GMAIL_FETCH_MAX_WORKERS = 4


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


def _classify_message(subject: str, body: str) -> tuple[str, str]:
    """Classify an employer reply with Jev alone — no model-routed LLM call.

    Confirms the rejection statement first, then the interview statement,
    against the same "subject\\n\\nbody" text a match is scored against,
    with the body truncated to 12000 characters so a large thread stays
    well under Jev's timeout instead of failing open to "other".
    Whichever confirms first wins; if neither confirms, the message is
    classified "other" and left for manual review. At most one Jev
    round-trip per statement — no retry, no second confirmation call.
    Never logs the email text. Returns ``(classification, suggested_status)``
    where suggested_status is "" for "other".
    """
    state = f"{subject}\n\n{body[:12000]}"
    rejection_statement, rejection_status = _CONFIRM_STATEMENTS["rejection"]
    if jev.confirm(rejection_statement, state):
        return "rejection", rejection_status
    interview_statement, interview_status = _CONFIRM_STATEMENTS["interview"]
    if jev.confirm(interview_statement, state):
        return "interview", interview_status
    return "other", ""


#: Statuses that mean a response has already been recorded (auto-applied or
#: otherwise) — the application is no longer worth scanning for an employer
#: reply. Everything else — including unrecognized/blank status strings — is
#: still a candidate, since status is an unvalidated str and we'd rather scan
#: a few extra applications than silently stop watching one.
CLOSED_STATUSES = {"Interviewing", "Offer", "Rejected"}


def _application_query(app, last_synced_at: float) -> str:
    """Gmail query scoped to one application's domains/company, after a cursor.

    Reuses matcher._app_domains — the same website/application_url domains
    and company token match_message later scores attribution against — so
    the query and the eventual attribution stay in sync. Also ORs in a
    quoted full-text search on the application's company name (with any
    double quotes stripped out first, so the quoted term can't be broken
    out of), so an application with a company but no usable domain (or a
    sender that doesn't match the domain heuristic) is still searched.
    Returns "" only when the application has neither domain nor company
    signal to search on, so the caller can skip it rather than issuing an
    unscoped query.
    """
    domains = _app_domains(app)
    company = str(getattr(app, "company", "") or "").replace('"', "").strip()
    has_company_signal = bool(_normalize(company))
    if not domains and not has_company_signal:
        return ""
    terms = [f"from:{d}" for d in sorted(domains)]
    if has_company_signal:
        terms.append(f'"{company}"')
    scoped = " OR ".join(terms)
    parts = [f"({scoped})"]
    if last_synced_at > 0:
        parts.append(f"after:{int(last_synced_at)}")
    return " ".join(parts)


def _pending_candidates():
    """Applications not yet in a closed status (Interviewing/Offer/Rejected).

    status is an unvalidated str, so this is a closed-set exclusion rather
    than an allowlist — anything not explicitly closed (Draft, Applied,
    Waiting, blank, or unrecognized) is still worth scanning. A Draft is
    also dropped when another non-Draft, non-closed candidate shares its
    normalized company name — that company is already watched via the
    other application, and leaving both in would tie the matcher's scoring
    (matcher.py is not touched) and cause match_message to return None,
    silently dropping the message and burning its id from processed_message_ids.
    """
    candidates = [app for app in load_all() if app.status not in CLOSED_STATUSES]
    watched_companies = {
        _normalize(str(getattr(app, "company", "") or ""))
        for app in candidates
        if app.status != "Draft"
    }
    watched_companies.discard("")
    return [
        app
        for app in candidates
        if app.status != "Draft" or _normalize(str(getattr(app, "company", "") or "")) not in watched_companies
    ]


def _sender_email(value: str) -> str:
    return parseaddr(value)[1].strip().lower()


def _sorted_pending(items: list[GmailSuggestion]) -> list[GmailSuggestion]:
    return sorted((item for item in items if item.state == "pending"), key=lambda item: item.date, reverse=True)


def current_state() -> GmailSyncState:
    return load_sync_state()


def pending_suggestions() -> list[GmailSuggestion]:
    return _sorted_pending(load_suggestions())


def _collect_message_ids(client: GmailClient, pending_apps: list, sync_state: GmailSyncState, processed_ids: set[str]) -> list[str]:
    """Distinct new message ids across every non-closed application's scoped query.

    Issues one Gmail query per non-closed application (skipping any with no
    domain or company signal), and dedupes ids already in ``processed_ids``
    or seen earlier in this same run — a message can legitimately match
    more than one application's query.

    The queries are built up front, in application order, then run
    concurrently on a bounded thread pool (GMAIL_FETCH_MAX_WORKERS workers)
    since each is an independent Gmail API round trip. Results are then
    merged into seen_ids/seen_set SERIALLY, one query's results at a time in
    that same application order, so the dedupe order — and which id "wins"
    when a message matches more than one query — stays identical to a plain
    serial run. Futures are also resolved in that order: if more than one
    query raised, the caller sees the same exception a serial run would have
    raised first (the earliest one in application order), not whichever
    query happened to fail first in wall-clock time.
    """
    queries: list[str] = []
    for app in pending_apps:
        query = _application_query(app, sync_state.last_synced_at)
        if query:
            queries.append(query)
    if not queries:
        return []
    logger.info(
        "gmail sync: dispatching %d list_messages queries (max_workers=%d)",
        len(queries),
        GMAIL_FETCH_MAX_WORKERS,
    )
    with ThreadPoolExecutor(max_workers=GMAIL_FETCH_MAX_WORKERS) as executor:
        futures = [executor.submit(client.list_messages, query) for query in queries]
    seen_ids: list[str] = []
    seen_set: set[str] = set()
    for future in futures:
        for item in future.result():
            message_id = str(item.get("id", ""))
            if not message_id or message_id in processed_ids or message_id in seen_set:
                continue
            seen_set.add(message_id)
            seen_ids.append(message_id)
    return seen_ids


# Classification -> (Jev confirmation statement, status to apply on confirm).
# Only these two classifications ever auto-apply a status; everything else
# (other) is left for the operator to review manually.
_CONFIRM_STATEMENTS = {
    "rejection": ("This email tells the candidate their job application was rejected.", "Rejected"),
    "interview": ("This email invites the candidate to interview for the job application.", "Interviewing"),
}


def _evidence_note(message_id: str, sender: str, subject: str, date: str) -> str:
    """One evidence paragraph documenting an auto-applied status change."""
    return (
        f"Gmail sync: status auto-updated from an employer reply "
        f'(message {message_id}, from {sender}, subject "{subject}", {date}).'
    )


def _apply_decision(app_id: str, status: str, message_id: str, sender: str, subject: str, date: str) -> None:
    """Set an application's status from a Jev-confirmed employer reply, with evidence."""
    app = get_application(app_id)
    existing_notes = (app.notes if app else "").strip()
    note = _evidence_note(message_id, sender, subject, date)
    notes = f"{existing_notes}\n\n{note}" if existing_notes else note
    update_application(app_id, {"status": status, "response_received": True, "notes": notes})


def _process_message(client: GmailClient, message_id: str, metadata: dict, pending_apps: list, by_id: dict[str, GmailSuggestion]) -> None:
    """Match and classify one already-fetched message; record a suggestion if matched.

    ``metadata`` is the message's get_metadata payload, fetched ahead of
    time by run_sync's prefetch (see run_sync) rather than fetched here —
    this function itself does no concurrent work, so classification,
    get_full, the by_id mutation, and _apply_decision all still run
    serially on the caller's thread, in application order.

    A rejection/interview classification is a Jev confirmation in itself
    (see _classify_message), so it auto-applies immediately — the matched
    application's status is updated with evidence in its notes and the
    suggestion is recorded as applied — but only when the match itself is
    not low-confidence (company keyword alone, score 2): a low-confidence
    match is too weak a link between message and application to act on
    unattended, so it stays a pending suggestion for the operator to apply
    by hand even though the classification is recorded. Any other
    classification is left pending and no application is touched.
    """
    sender = _header(metadata, "From")
    subject = _header(metadata, "Subject")
    date = _header(metadata, "Date")
    snippet = str(metadata.get("snippet", ""))
    match = match_message(pending_apps, sender=sender, subject=subject, snippet=snippet)
    if match is None:
        return
    full = client.get_full(message_id)
    body = _decode_body(full.get("payload") or {})
    classification, suggested_status = _classify_message(subject, body)
    if message_id in by_id:
        return
    decision = ""
    suggestion_state = "pending"
    if suggested_status and match.confidence != "low":
        _apply_decision(match.application_id, suggested_status, message_id, sender, subject, date)
        suggestion_state = "applied"
        decision = "confirmed"
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
        state=suggestion_state,
        decision=decision,
    )


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
    client = build_gmail_client()
    existing = load_suggestions()
    by_id = {item.id: item for item in existing}
    processed_ids = set(sync_state.processed_message_ids)
    pending_apps = _pending_candidates()
    new_processed = _collect_message_ids(client, pending_apps, sync_state, processed_ids)
    if new_processed:
        # Prefetch get_metadata for every new message id concurrently, bounded
        # by GMAIL_FETCH_MAX_WORKERS, then hand the results to _process_message
        # one at a time, in the same order as new_processed. Resolving each
        # future before moving to the next keeps classification, get_full,
        # the by_id mutation, and _apply_decision on the main thread and in
        # application order — identical side effects and, if a fetch raised,
        # the same exception a serial run would have surfaced first.
        logger.info(
            "gmail sync: prefetching metadata for %d messages (max_workers=%d)",
            len(new_processed),
            GMAIL_FETCH_MAX_WORKERS,
        )
        with ThreadPoolExecutor(max_workers=GMAIL_FETCH_MAX_WORKERS) as executor:
            metadata_futures = [(message_id, executor.submit(client.get_metadata, message_id)) for message_id in new_processed]
        for message_id, future in metadata_futures:
            metadata = future.result()
            _process_message(client, message_id, metadata, pending_apps, by_id)
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
