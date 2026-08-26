"""Validation for a job posting's captured body text.

A screening is only actionable at approval time if the operator has enough
of the original posting to draft a cover letter from days later — on a page
the capturing agent never sees. This module provides a strict check for
that captured text, kept standalone and deliberately separate from
``screening.store`` — the store stays lenient so the legacy importer
(``scripts/migrate_jobs_history.py``) can bring in historical records that
predate this requirement, exactly as ``screening.role`` and
``screening.company`` do for their fields.
"""

from __future__ import annotations

# Minimum length, in characters, for normalized posting text to be considered
# a real posting body rather than a stub, an error message, or noise. Cheap
# to retune — used nowhere else.
MIN_POSTING_TEXT_CHARS = 200

# Below this length, a junk-phrase match is treated as evidence the captured
# text IS the junk page (a login wall, a 404, a cookie banner) rather than a
# genuine posting that happens to mention e.g. cookies in passing.
_JUNK_PHRASE_MAX_TEXT_CHARS = 1200

# Phrases that indicate the captured text is a wall/error page rather than a
# real posting body. Matched case-insensitively via ``str.casefold``; all
# lowercase.
_JUNK_PHRASES = frozenset(
    {
        "sign in to view",
        "log in to continue",
        "enable javascript",
        "we use cookies",
        "accept cookies",
        "page not found",
        "404",
        "no longer available",
        "no longer accepting applications",
        "position has been filled",
        "access denied",
        "verify you are human",
        "checking your browser",
    }
)

# Length an offending value is truncated to when quoted in a rejection message.
_EXCERPT_LENGTH = 120


def normalize_posting_text(text: str) -> str:
    """Return ``text`` with whitespace collapsed and edges stripped.

    All runs of whitespace (newlines, tabs, non-breaking spaces) collapse to
    a single space, and the result is stripped. Never raises: a non-``str``
    input (e.g. ``None`` or an ``int``) yields ``""``.
    """
    if not isinstance(text, str):
        return ""
    return " ".join(text.split())


def _excerpt(text: str) -> str:
    """Return a truncated, ellipsis-suffixed excerpt of ``text`` for messages."""
    if len(text) <= _EXCERPT_LENGTH:
        return text
    return text[:_EXCERPT_LENGTH] + "…"


def _find_junk_phrase(casefolded: str) -> str | None:
    """Return the first junk phrase found in ``casefolded``, or ``None``."""
    for phrase in _JUNK_PHRASES:
        if phrase in casefolded:
            return phrase
    return None


def validate_posting_text(text: str) -> str:
    """Return the normalized posting text, or raise ``ValueError`` if unusable.

    Usable text is non-empty after normalization, at least
    ``MIN_POSTING_TEXT_CHARS`` long, and does not look like a wall/error page
    (a login prompt, a cookie banner, a 404) rather than a genuine posting —
    that last check only fires when the text is also short
    (``< _JUNK_PHRASE_MAX_TEXT_CHARS``), so a long real posting that merely
    mentions cookies in passing is not rejected. Each rejection has its own
    message; all but the empty case include a truncated excerpt of the
    offending value.
    """
    stripped = normalize_posting_text(text)
    if not stripped:
        raise ValueError(
            "Posting text is required — the operator drafts the cover letter "
            "from this text days later, on a page the agent never sees."
        )
    if len(stripped) < MIN_POSTING_TEXT_CHARS:
        raise ValueError(
            f"Posting text is too short to be a real posting ({len(stripped)} "
            f"chars, need at least {MIN_POSTING_TEXT_CHARS}): {_excerpt(stripped)!r}"
        )
    if len(stripped) < _JUNK_PHRASE_MAX_TEXT_CHARS:
        junk = _find_junk_phrase(stripped.casefold())
        if junk is not None:
            raise ValueError(
                "Posting text looks like a wall/error page, not a job posting "
                f"(matched {junk!r}): {_excerpt(stripped)!r}"
            )
    return stripped
