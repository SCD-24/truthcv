"""The Screenings page's paged ledger: one page of every screening record.

Owns the paging, filter and sort policy for GET /api/screenings/ledger so the
route only parses its query and maps records to the wire model. Everything is
computed from ONE ``load_all`` read, so the page, the total and the last
activity all describe the same file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from truthcv.domain.screening import store as screening_store
from truthcv.domain.screening.model import Screening

# Bounds for the ledger page size: the requested limit is clamped into them.
LEDGER_MIN_LIMIT = 1
LEDGER_MAX_LIMIT = 200


@dataclass
class LedgerPage:
    """One page of the screening ledger plus the effective (clamped) bounds.

    ``total`` counts records after the ``blocked_only`` filter;
    ``last_activity`` covers every record, filtered out or not.
    """

    rows: list[Screening]
    total: int
    limit: int
    offset: int
    last_activity: str | None


def _activity_time(raw: str) -> datetime | None:
    """``raw`` as an aware datetime, or None when it does not parse.

    A value with no offset is read as UTC.
    """
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def last_activity(screenings: list[Screening]) -> str | None:
    """The raw date string of the newest activity across ``screenings``.

    Mirrors ``lastAgentActivity`` in web/src/settings/agentActivity.ts: each
    record contributes its ``screened_date``, falling back to ``created_at``
    when that is empty; records with no usable, parseable date are skipped.
    None when no record has one.
    """
    best: tuple[datetime, str] | None = None
    for screening in screenings:
        raw = screening.screened_date or screening.created_at
        time = _activity_time(raw) if raw else None
        if time is not None and (best is None or time > best[0]):
            best = (time, raw)
    return best[1] if best else None


def ledger_page(limit: int, offset: int, blocked_only: bool = False) -> LedgerPage:
    """One page of screenings, newest ``created_at`` first.

    ``blocked_only`` keeps only records with a non-empty
    ``screening_blocker``. limit is clamped into [LEDGER_MIN_LIMIT,
    LEDGER_MAX_LIMIT] and a negative offset to 0; the effective values are
    returned for the caller to echo back.
    """
    screenings = screening_store.load_all()
    limit = min(max(limit, LEDGER_MIN_LIMIT), LEDGER_MAX_LIMIT)
    offset = max(0, offset)
    rows = sorted(screenings, key=lambda s: s.created_at, reverse=True)
    if blocked_only:
        rows = [s for s in rows if s.screening_blocker]
    return LedgerPage(
        rows=rows[offset : offset + limit],
        total=len(rows),
        limit=limit,
        offset=offset,
        last_activity=last_activity(screenings),
    )
