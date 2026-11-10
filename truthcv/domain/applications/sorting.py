"""Server-side application sorting logic, mirroring web/src/applications/sorting.ts.

Sorts applications by the same semantics used on the frontend, enabling
server-side pagination with consistent ordering across pages.
"""

from functools import cmp_to_key
from urllib.parse import urlparse

# Order applications by status; lower index sorts first. Unlisted/unset
# statuses (e.g. "") fall to the bottom.
STATUS_ORDER = [
    "Offer",
    "Interviewing",
    "Waiting",
    "Applied",
    "Draft",
    "Rejected",
]


def status_rank(status: str) -> int:
    """Return the sort rank of a status, with unlisted statuses at the bottom."""
    try:
        return STATUS_ORDER.index(status)
    except ValueError:
        return len(STATUS_ORDER)


def _parse_url_host(url: str | None) -> str:
    """Extract the host from a URL, or return the URL as-is if parsing fails."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url


def _text_compare(av: str, bv: str) -> int:
    """Compare two text values: case-insensitive, blanks last ascending."""
    av = (av or "").strip()
    bv = (bv or "").strip()
    if not av and not bv:
        return 0
    if not av:
        return 1  # blanks last in ascending
    if not bv:
        return -1
    av_lower = av.lower()
    bv_lower = bv.lower()
    if av_lower < bv_lower:
        return -1
    elif av_lower > bv_lower:
        return 1
    else:
        return 0


def _bool_compare(a_val: bool, b_val: bool) -> int:
    """Compare two booleans: yes-first ascending."""
    return int(bool(b_val)) - int(bool(a_val))


def _presence_compare(a_val, b_val) -> int:
    """Compare presence of two values: items with value come first ascending."""
    return int(bool(b_val)) - int(bool(a_val))


# Mapping from sort key name to (comparator, blank_fn) tuple
# Each sort key has a function that takes two applications and returns -1/0/1
SORT_COMPARATORS = {
    "company": (lambda a, b: _text_compare(a.company, b.company), None),
    "date": (lambda a, b: _text_compare(a.application_date, b.application_date), 
             lambda a: not (a.application_date or "").strip()),
    "website": (lambda a, b: _text_compare(_parse_url_host(a.website), _parse_url_host(b.website)), None),
    "url": (lambda a, b: _presence_compare(a.application_url, b.application_url), None),
    "submitted": (lambda a, b: _bool_compare(a.submitted, b.submitted), None),
    "type": (lambda a, b: _text_compare(a.submission_type, b.submission_type), None),
    "status": (lambda a, b: status_rank(a.status) - status_rank(b.status), None),
    "reachedOut": (lambda a, b: _bool_compare(a.reached_out, b.reached_out), None),
    "toWho": (lambda a, b: _text_compare(a.to_who, b.to_who), None),
    "response": (lambda a, b: _bool_compare(a.response_received, b.response_received), None),
    "method": (lambda a, b: _text_compare(a.method, b.method), None),
    "notes": (lambda a, b: _text_compare(a.notes, b.notes), None),
    "posting": (lambda a, b: _presence_compare(a.posting, b.posting), None),
    "documents": (lambda a, b: _presence_compare(a.cv_document or a.cover_letter_document, 
                                                    b.cv_document or b.cover_letter_document), None),
    "filledForm": (lambda a, b: _presence_compare(a.fields_submitted, b.fields_submitted), None),
}

DEFAULT_SORT = "date"
DEFAULT_DIRECTION = "desc"


def sort_applications(apps: list, sort: str = DEFAULT_SORT, direction: str = DEFAULT_DIRECTION) -> list:
    """Sort a list of applications by the given column and direction.

    Args:
        apps: The applications to sort.
        sort: The sort key (e.g. "company", "date"). Defaults to "date".
        direction: "asc" or "desc". Defaults to "desc".

    Returns:
        A new sorted list.

    Raises:
        ValueError: If the sort key or direction is invalid.
    """
    if sort not in SORT_COMPARATORS:
        raise ValueError(f"Unknown sort key: {sort}")
    if direction not in ("asc", "desc"):
        raise ValueError(f"Invalid sort direction: {direction}. Must be 'asc' or 'desc'")

    compare_fn, blank_fn = SORT_COMPARATORS[sort]

    def compare(a, b):
        # Blanks are decided before the direction is applied, so the negation
        # below cannot lift blanks to the top of a descending sort.
        if blank_fn:
            a_blank = blank_fn(a)
            b_blank = blank_fn(b)
            if a_blank != b_blank:
                return 1 if a_blank else -1

        result = compare_fn(a, b)
        return -result if direction == "desc" else result

    return sorted(apps, key=cmp_to_key(compare))
