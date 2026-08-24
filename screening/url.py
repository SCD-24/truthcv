"""Validation for a job posting URL.

A screening is only actionable if the operator can open the posting it came
from. This module provides a strict check for that URL, kept standalone and
deliberately separate from ``screening.store`` — the store stays lenient about
urls so the legacy importer (``scripts/migrate_jobs_history.py``) can bring in
historical records that predate this requirement.
"""

from __future__ import annotations

from urllib.parse import urlparse


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
