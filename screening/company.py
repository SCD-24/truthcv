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

import re

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


# Legal-entity suffixes stripped from the END of a company name (only, and
# only on a word boundary) to build an identity key. Sourced from common
# German, UK/US, and other European entity designations. Lowercase; matched
# case-insensitively against the already-casefolded name.
_LEGAL_SUFFIXES = frozenset(
    {
        "gmbh",
        "mbh",
        "gmbh & co. kg",
        "ag",
        "se",
        "kg",
        "ug",
        "ltd",
        "ltd.",
        "limited",
        "inc",
        "inc.",
        "llc",
        "corp",
        "corp.",
        "co",
        "co.",
        "plc",
        "bv",
        "b.v.",
        "nv",
        "n.v.",
        "sa",
        "s.a.",
        "sas",
        "srl",
        "spa",
        "oy",
        "ab",
        "as",
        "a/s",
        "aps",
        "kft",
        "sp. z o.o.",
        "pty",
    }
)

# Suffixes ordered longest-first so a compound suffix like "gmbh & co. kg" is
# tried before its trailing component "kg" would otherwise match instead.
_LEGAL_SUFFIXES_BY_LENGTH = sorted(_LEGAL_SUFFIXES, key=len, reverse=True)

# Cap on suffix-stripping iterations so a pathological input (e.g. many
# chained suffix-like words) cannot loop unboundedly.
_MAX_SUFFIX_STRIP_ITERATIONS = 6


def _strip_one_trailing_suffix(key: str) -> str | None:
    """Strip one legal-entity suffix from the end of ``key``, or return ``None``.

    Matches only at the very end of the string and only when the suffix is a
    whole "word" (preceded by whitespace or the start of the string), so a
    suffix embedded mid-string or inside parentheses is never touched. An
    optional trailing "." beyond the suffix itself is tolerated (so both
    "gmbh" and "gmbh." strip the same way). Returns ``None`` when no suffix
    matches, or when stripping the match would leave nothing behind (a name
    that *is* only a suffix, e.g. "Limited", is left alone by the caller).
    """
    for suffix in _LEGAL_SUFFIXES_BY_LENGTH:
        pattern = r"(?:^|(?<=\s))" + re.escape(suffix) + r"\.?$"
        match = re.search(pattern, key)
        if not match:
            continue
        candidate = key[: match.start()].strip(_SEPARATORS + " \t.,&/")
        candidate = " ".join(candidate.split())
        if candidate:
            return candidate
        return None
    return None


def company_identity_key(company: str) -> str:
    """Return a comparison-only identity key that ignores legal-entity suffixes.

    This is an IDENTITY key for COMPARING companies (cooldown matching, the
    blocklist, target-company matching, and de-duplicating application
    records) — it deliberately collapses "RobCo" and "RobCo GmbH" to the same
    key so a legal-entity suffix does not manufacture a second employer. It
    is never stored as a company's name and never shown to a user;
    ``normalize_company_name``/``validate_company_name`` remain the
    validated display/storage form.

    Built by casefolding ``normalize_company_name(company)`` and then
    repeatedly stripping a trailing legal-entity suffix (matched only at the
    end of the string and only on a word boundary, so "Klar (Klar
    Technologies GmbH)" and "Noxtua (Xayn AG)" — where the suffix sits inside
    parentheses, not at the true end — are left unchanged apart from
    casefolding). Suffix-stripping is capped and applied repeatedly so a
    compound like "Foo GmbH & Co. KG" reduces cleanly to "foo".

    Never raises: a non-``str`` input yields ``""``. For any non-empty input,
    the result is always non-empty — if stripping would leave nothing behind
    (a name that is only a suffix, e.g. "Limited"), the un-stripped
    casefolded form is returned instead.
    """
    if not isinstance(company, str):
        return ""
    normalized = normalize_company_name(company)
    if not normalized:
        return ""
    key = normalized.casefold()
    for _ in range(_MAX_SUFFIX_STRIP_ITERATIONS):
        stripped = _strip_one_trailing_suffix(key)
        if stripped is None or stripped == key:
            break
        key = stripped
    if not key:
        return normalized.casefold()
    return key


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
