"""Read-only screening tools for the diagnostics MCP endpoint.

list_screenings summarises and filters; get_screening pages the full stored
posting_text; search_screening_text literal-searches within it. None write.
"""

from __future__ import annotations

import re

import screening.store as _screening_store
from api.diagnostics_paging import _clamp_limit

_POSTING_TEXT_PAGE_DEFAULT = 8000
_POSTING_TEXT_PAGE_MAX = 20000
_SEARCH_CONTEXT_DEFAULT = 200
_SEARCH_CONTEXT_MAX = 1000
_SEARCH_MATCHES_DEFAULT = 20
_SEARCH_MATCHES_MAX = 50


def _screening_summary(s) -> dict:
    """A read-only summary of one screening, with only posting_text's length."""
    return {
        "id": s.id,
        "company": s.company,
        "role": s.role,
        "url": s.url,
        "screened_date": s.screened_date,
        "verdict": s.verdict,
        "screening_blocker": s.screening_blocker,
        "approval": s.approval,
        "profile": s.profile,
        "run_id": s.run_id,
        "posting_text_length": len(s.posting_text or ""),
    }


def _sort_key(s) -> str:
    """Newest-created-first ordering key, falling back to screened_date."""
    if s.created_at:
        return s.created_at
    return f"{s.screened_date}T00:00:00+00:00" if s.screened_date else ""


def _matches(s, url_contains: str, text_contains: str, exact: dict) -> bool:
    """Whether screening `s` passes every non-empty filter."""
    if url_contains and url_contains.lower() not in (s.url or "").lower():
        return False
    if text_contains and text_contains.lower() not in (s.posting_text or "").lower():
        return False
    return all(getattr(s, attr) == want for attr, want in exact.items() if want)


def list_screenings(
    limit: int = 0,
    offset: int = 0,
    url_contains: str = "",
    screening_blocker: str = "",
    verdict: str = "",
    approval: str = "",
    run_id: str = "",
    text_contains: str = "",
) -> dict:
    """A filtered, summarised page of screenings, newest-created first.

    `url_contains` and `text_contains` (matched against posting_text) are
    case-insensitive literal substrings; the other filters are exact
    matches; empty means no filter. `total` is the filtered count, before
    paging. `limit` is clamped by `_clamp_limit` (default 20, cap 200;
    <=0 means the default). Entries carry `posting_text_length`, not text.
    """
    exact = {"screening_blocker": screening_blocker, "verdict": verdict,
             "approval": approval, "run_id": run_id}
    records = sorted(_screening_store.load_all(), key=_sort_key, reverse=True)
    records = [s for s in records if _matches(s, url_contains, text_contains, exact)]
    total = len(records)
    if offset > 0:
        records = records[offset:]
    records = records[:_clamp_limit(limit)]
    return {"total": total, "screenings": [_screening_summary(s) for s in records]}


def get_screening(screening_id: str, offset: int = 0, limit: int = 8000) -> dict:
    """One screening (minus posting_text) plus a bounded page of posting_text.

    Returns {} for an unknown id. `limit` <=0 means 8000 and is capped at
    20000; a negative `offset` is treated as 0. `next_offset` is None once
    the text is exhausted.
    """
    s = _screening_store.get(screening_id)
    if s is None:
        return {}
    text = s.posting_text or ""
    start = max(offset, 0)
    size = _POSTING_TEXT_PAGE_DEFAULT if limit <= 0 else min(limit, _POSTING_TEXT_PAGE_MAX)
    end = start + size
    record = s.to_dict()
    record.pop("posting_text", None)
    return {
        "screening": record,
        "posting_text": {
            "total_length": len(text),
            "offset": start,
            "text": text[start:end],
            "next_offset": end if end < len(text) else None,
        },
    }


def _bound(value: int, default: int, maximum: int) -> int:
    """<=0 yields `default`; otherwise cap at `maximum`."""
    return default if value <= 0 else min(value, maximum)


def search_screening_text(
    screening_id: str, query: str, context_chars: int = 200, max_matches: int = 20
) -> dict:
    """Literal, case-insensitive search within a screening's posting_text.

    Returns {} for an unknown id and {"error": ...} for a blank query.
    `context_chars` <=0 means 200 (max 1000); `max_matches` <=0 means 20
    (max 50). Matches are non-overlapping; `truncated` is true when more
    matches exist than were returned.
    """
    s = _screening_store.get(screening_id)
    if s is None:
        return {}
    if not query or not query.strip():
        return {"error": "query must be non-empty"}
    text = s.posting_text or ""
    ctx = _bound(context_chars, _SEARCH_CONTEXT_DEFAULT, _SEARCH_CONTEXT_MAX)
    cap = _bound(max_matches, _SEARCH_MATCHES_DEFAULT, _SEARCH_MATCHES_MAX)
    # Count every match but keep only the first `cap`, so a huge posting
    # never materialises an unbounded list of match objects.
    total = 0
    matches = []
    for m in re.finditer(re.escape(query), text, re.IGNORECASE):
        total += 1
        if total <= cap:
            begin = max(0, m.start() - ctx)
            matches.append({"offset": m.start(), "context_start": begin,
                            "context": text[begin:m.end() + ctx]})
    return {"total_length": len(text), "query": query, "total_matches": total,
            "matches": matches, "truncated": total > len(matches)}
