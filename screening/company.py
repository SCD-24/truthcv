"""Validation for the employing company's name on a screening record.

A screening is only actionable if the operator knows who the employer is: the
cooldown rules match on company, the blocklist matches on company, and the
approval queue is unreadable without it. This module provides a strict check
for that name, kept standalone and deliberately separate from
``screening.store`` — the store stays lenient so the legacy importer
(``scripts/migrate_jobs_history.py``) can bring in historical records that
predate this requirement, exactly as ``screening.role`` does for titles.
"""

from __future__ import annotations

# Placeholder phrases agents and job boards emit in place of a real employer
# name. Matched case-insensitively via ``str.casefold``; all lowercase.
_PLACEHOLDERS = frozenset(
    {
        "n/a",
        "na",
        "none",
        "null",
        "unknown",
        "tbd",
        "company",
        "the company",
        "employer",
        "confidential",
        "undisclosed",
        "not stated",
        "not specified",
        "see posting",
        "see description",
        "various",
        "-",
        "--",
    }
)

# Separator punctuation stripped from the very ends of a name.
_SEPARATORS = "-–—|·,:;"


def normalize_company_name(company: str) -> str:
    """Return ``company`` with whitespace collapsed and edge separators removed.

    All runs of whitespace (newlines, tabs, non-breaking spaces) collapse to a
    single space, the result is stripped, and leading/trailing separator
    punctuation is stripped from the ends only. Never raises: a non-``str``
    input (e.g. ``None`` or an ``int``) yields ``""``.
    """
    if not isinstance(company, str):
        return ""
    collapsed = " ".join(company.split())
    return collapsed.strip(_SEPARATORS + " \t").strip()


def validate_company_name(company: str) -> str:
    """Return the normalized name, or raise ``ValueError`` if unusable.

    A usable name is non-empty after normalization, is not a pasted URL, is
    short enough to be a name rather than a sentence, contains at least one
    letter, and is not a placeholder. Each rejection has its own message; all
    but the empty case include the offending value.
    """
    stripped = normalize_company_name(company)
    if not stripped:
        raise ValueError(
            "A company name is required — cooldown, the blocklist and the "
            "approval queue all match on the employer, and cannot without it."
        )
    if "://" in stripped or stripped.startswith("www."):
        raise ValueError(f"Not a valid company name (looks like a URL): {stripped!r}")
    if len(stripped) > 120:
        raise ValueError(
            f"Not a valid company name (too long to be a name): {stripped!r}"
        )
    if not any(ch.isalpha() for ch in stripped):
        raise ValueError(f"Not a valid company name (no letters): {stripped!r}")
    if stripped.casefold() in _PLACEHOLDERS:
        raise ValueError(
            "Not a valid company name (looks like placeholder text, not an "
            f"employer): {stripped!r}"
        )
    return stripped
