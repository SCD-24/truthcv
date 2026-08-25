"""Validation for a job posting URL.

A screening is only actionable if the operator can open the posting it came
from. This module provides a strict check for that URL, kept standalone and
deliberately separate from ``screening.store`` — the store stays lenient about
urls so the legacy importer (``scripts/migrate_jobs_history.py``) can bring in
historical records that predate this requirement.
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

_APPLICATION_SEGMENTS = frozenset(
    {"apply", "application", "applications", "apply-now"}
)


def validate_posting_url(url: str) -> str:
    """Return ``url`` stripped, or raise ``ValueError`` if it is unusable.

    A usable posting URL is non-empty after stripping, has an ``http`` or
    ``https`` scheme, and names a host. Anything else raises ``ValueError``:
    an empty input has its own message, and a malformed URL is reported with
    the offending value included.
    """
    stripped = url.strip()
    if not stripped:
        raise ValueError(
            "A posting URL is required — a screening the operator cannot open "
            "cannot be applied to."
        )

    parsed = urlparse(stripped)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Not a valid posting URL: {stripped!r}")

    return stripped


def normalize_application_url(url: str) -> str:
    """Return a normalized form of ``url`` for equality comparison.

    The "already applied" guard compares the URL of the screening being worked
    against the URL recorded when the operator applied. Those two strings refer
    to the same posting but are rarely byte-identical: the screening might hold
    ``https://x.example.com/j/4d090169-xxxx/`` while the recorded application
    URL is ``https://x.example.com/j/4d090169-xxxx/application`` — same job,
    different trailing segment — so the guard never matched and let duplicate
    applications through. This function collapses such cosmetic differences
    (scheme/host case, tracking query params, a trailing slash, and a trailing
    ``apply``/``application`` segment) to a canonical string so the pair
    compares equal.

    This is a matching helper, not a validator: it never raises. An empty or
    unparseable input yields ``""``.
    """
    stripped = url.strip()
    if not stripped:
        return ""

    try:
        parsed = urlparse(stripped)
    except ValueError:
        return ""

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    path = parsed.path
    # Strip exactly one trailing slash.
    if path.endswith("/"):
        path = path[:-1]
    # Strip exactly one trailing application-ish segment.
    head, sep, last = path.rpartition("/")
    if sep and last.lower() in _APPLICATION_SEGMENTS:
        path = head

    # Drop the query string and fragment.
    return urlunparse((scheme, netloc, path, parsed.params, "", ""))
