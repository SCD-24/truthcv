"""Validation for a job posting's role title.

A screening is only actionable if the operator knows which role it is for —
they screen candidates on the title. This module provides a strict check for
that title, kept standalone and deliberately separate from ``screening.store``
— the store stays lenient about titles so the legacy importer
(``scripts/migrate_jobs_history.py``) can bring in historical records that
predate this requirement.
"""

from __future__ import annotations

# Placeholder phrases job boards and scraping agents commonly emit in place of a
# real title. Matched case-insensitively via ``str.casefold``; all lowercase.
_BOARD_NOISE = frozenset(
    {
        "apply",
        "apply now",
        "view job",
        "view details",
        "save job",
        "job",
        "jobs",
        "position",
        "vacancy",
        "n/a",
        "na",
        "none",
        "unknown",
        "tbd",
        "see posting",
        "see description",
        "full time",
        "full-time",
        "part time",
        "part-time",
        "remote",
        "hybrid",
        "onsite",
        "on-site",
    }
)

# Separator punctuation stripped from the very ends of a title.
_SEPARATORS = "-–—|·,:;"


def _strip_separators(text: str) -> str:
    """Strip leading/trailing separator punctuation and its surrounding space."""
    return text.strip(_SEPARATORS + " \t").strip()


def normalize_role_title(role: str) -> str:
    """Return ``role`` with whitespace collapsed and edge separators removed.

    All runs of whitespace (newlines, tabs, non-breaking spaces) collapse to a
    single space, the result is stripped, and leading/trailing separator
    punctuation is stripped from the ends only. Never raises: a non-``str``
    input (e.g. ``None`` or an ``int``) yields ``""``.
    """
    if not isinstance(role, str):
        return ""
    collapsed = " ".join(role.split())
    return _strip_separators(collapsed)


def validate_role_title(role: str) -> str:
    """Return the normalized title, or raise ``ValueError`` if unusable.

    A usable title is non-empty after normalization, is not a pasted URL, is
    short enough to be a title, contains at least one letter, and is not a
    board-noise placeholder. Each rejection has its own message; all but the
    empty case include the offending value.
    """
    stripped = normalize_role_title(role)
    if not stripped:
        raise ValueError(
            "A job title is required — the operator screens candidates on the "
            "role, and cannot without it."
        )
    if "://" in stripped or stripped.startswith("www."):
        raise ValueError(f"Not a valid job title (looks like a URL): {stripped!r}")
    if len(stripped) > 120:
        raise ValueError(f"Not a valid job title (too long to be a title): {stripped!r}")
    if not any(ch.isalpha() for ch in stripped):
        raise ValueError(f"Not a valid job title (no letters): {stripped!r}")
    if stripped.casefold() in _BOARD_NOISE:
        raise ValueError(
            f"Not a valid job title (looks like placeholder text, not a title): {stripped!r}"
        )
    return stripped
