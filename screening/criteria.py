"""Validation and matching for a posting's stated criteria against a profile.

A screening records not just a verdict but the evidence behind it: what the
posting itself said about remote work and required languages, so a rejection
can be explained in terms the operator can check against the posting later.
This module is standalone, like ``screening.posting`` and ``screening.role``,
and is deliberately not imported by ``screening.model`` — the dataclass stays
a plain data shape; only ``screening.store`` normalises against it.
"""

from __future__ import annotations

import re

# The posting's own stated remote arrangement. "" means the field was not
# supplied at all; "unstated" means the agent read the posting and it simply
# did not say — the two are kept distinct because a caller may care which.
REMOTE_ARRANGEMENT_VALUES = ("", "remote", "hybrid", "on_site", "unstated")

# Aliases job boards and postings commonly use for "on_site", normalised
# before comparison against REMOTE_ARRANGEMENT_VALUES.
_ON_SITE_ALIASES = frozenset({"onsite", "on-site", "office"})

# Free-text language requirement values that mean "no requirement stated".
_NO_LANGUAGE_VALUES = frozenset(
    {"", "none", "unstated", "not stated", "n/a", "any"}
)

# Profile remote-model values that only accept a posting arrangement drawn
# from a limited set; any value not a key here (including None/"") accepts
# any arrangement.
_COMPATIBLE_ARRANGEMENTS = {
    "remote": frozenset({"remote", "unstated", ""}),
    "hybrid": frozenset({"remote", "hybrid", "unstated", ""}),
}


def validate_remote_arrangement(value: str) -> str:
    """Return the normalized remote arrangement, or raise ``ValueError``.

    Normalisation strips whitespace and casefolds, then maps the common
    aliases "onsite"/"on-site"/"office" to "on_site". The result must be one
    of ``REMOTE_ARRANGEMENT_VALUES``.
    """
    cleaned = value.strip().casefold() if isinstance(value, str) else ""
    if cleaned in _ON_SITE_ALIASES:
        cleaned = "on_site"
    if cleaned not in REMOTE_ARRANGEMENT_VALUES:
        raise ValueError(
            f"Unknown remote arrangement {value!r}. Use one of: "
            f"{', '.join(REMOTE_ARRANGEMENT_VALUES)}."
        )
    return cleaned


def validate_language_requirement(value: str) -> str:
    """Return the normalized language requirement, or "" if none is stated.

    Normalisation collapses whitespace and lowercases; "" and "none" (either
    case) both normalise to "" — the posting stated no required language.
    Never raises: any free-text value is accepted as-is once normalised.
    """
    cleaned = " ".join(value.split()).casefold() if isinstance(value, str) else ""
    if cleaned in _NO_LANGUAGE_VALUES:
        return ""
    return cleaned


def _normalise_remote_model(value: str) -> str:
    """Normalise a free-text profile remote-model value for comparison.

    Same normalisation as ``validate_remote_arrangement`` (strip, casefold,
    map the "onsite"/"on-site"/"office" aliases to "on_site"), but never
    raises: ``JobProfile.remote_model`` is a plain free-text field, not a
    validated enum, so an unrecognised value is returned as-is (casefolded)
    for the "accepts anything" fallback in ``remote_compatible`` to handle.
    """
    cleaned = value.strip().casefold() if isinstance(value, str) else ""
    if cleaned in _ON_SITE_ALIASES:
        cleaned = "on_site"
    return cleaned


def remote_compatible(profile_remote_model: str | None, arrangement: str) -> bool:
    """Whether a posting's stated ``arrangement`` fits ``profile_remote_model``.

    A profile of 'remote' accepts only a posting stated (or known to be)
    remote/unstated/"". A profile of 'hybrid' additionally accepts hybrid.
    'on_site', any other value, and an empty/None profile accept any
    arrangement — there is nothing to conflict with. The profile value is a
    plain free-text field (the Agents page's TextField), so it is normalised
    the same way the posting's own arrangement is before the lookup: "Remote"
    or " remote " must match 'remote', not fall through to "accepts anything".
    """
    if not profile_remote_model:
        return True
    allowed = _COMPATIBLE_ARRANGEMENTS.get(_normalise_remote_model(profile_remote_model))
    if allowed is None:
        return True
    return arrangement in allowed


# Splits a free-text ``working_language`` value into its individual
# languages: commas, slashes, and the words "or"/"and" all separate
# alternatives ("English or German", "English/German", "English, German").
_LANGUAGE_SPLIT_RE = re.compile(r"[,/]|\bor\b|\band\b", flags=re.IGNORECASE)


def _split_languages(working_language: str) -> list[str]:
    """Split a profile's free-text ``working_language`` into acceptable tokens.

    Each piece is normalised via ``validate_language_requirement``; empty
    pieces (from e.g. a trailing separator) are dropped.
    """
    pieces = _LANGUAGE_SPLIT_RE.split(working_language)
    return [
        normalised
        for piece in pieces
        if (normalised := validate_language_requirement(piece))
    ]


def language_compatible(working_language: str | None, requirement: str) -> bool:
    """Whether a posting's stated language ``requirement`` fits the profile.

    True when the profile has no working language, the posting states no
    requirement, or the requirement matches one of the profile's acceptable
    languages (case/whitespace-insensitively, via the same normalisation as
    ``validate_language_requirement``). The profile's ``working_language`` is
    a plain free-text field and may name more than one acceptable language
    ("English or German", "English/German", "English, German" all split into
    a set of alternatives); compatible when the requirement matches ANY of
    them. No fuzzy matching: "German" and "Deutsch" are not considered the
    same.
    """
    if not working_language:
        return True
    # Normalise BEFORE the emptiness test: "unstated"/"none"/"n/a" are
    # spellings of "the posting states no requirement" and must take the
    # compatible path, not be compared literally against the profile.
    normalised_requirement = validate_language_requirement(requirement)
    if not normalised_requirement:
        return True
    return normalised_requirement in _split_languages(working_language)


def evaluate(
    profile_remote_model: str | None,
    working_language: str | None,
    arrangement: str,
    requirement: str,
) -> tuple[str, str]:
    """Check a posting's stated criteria against a profile; return the verdict evidence.

    Returns ``("", "")`` when the posting is compatible with the profile on
    both criteria. Otherwise returns ``(failing_criterion, reason)`` where
    ``failing_criterion`` is ``"remote_model"`` or ``"working_language"`` and
    ``reason`` is a one-line, human-readable explanation naming both the
    profile's value and the posting's stated evidence. Remote is checked
    before language, so a posting failing both reports the remote mismatch.
    """
    if not remote_compatible(profile_remote_model, arrangement):
        return (
            "remote_model",
            f"Profile requires {profile_remote_model!r} but the posting states "
            f"remote arrangement {arrangement!r}.",
        )
    if not language_compatible(working_language, requirement):
        return (
            "working_language",
            f"Profile working language is {working_language!r} but the posting "
            f"explicitly requires {requirement!r}.",
        )
    return ("", "")
