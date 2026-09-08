"""Validation and matching for a posting's stated criteria against a profile.

A screening records not just a verdict but the evidence behind it: what the
posting itself said about remote work and required languages, so a rejection
can be explained in terms the operator can check against the posting later.
This module is standalone, like ``screening.posting`` and ``screening.role``,
and is deliberately not imported by ``screening.model`` — the dataclass stays
a plain data shape; only ``screening.store`` normalises against it.
"""

from __future__ import annotations

# The posting's own stated remote arrangement. "" means the field was not
# supplied at all; "unstated" means the agent read the posting and it simply
# did not say — the two are kept distinct because a caller may care which.
REMOTE_ARRANGEMENT_VALUES = ("", "remote", "hybrid", "on_site", "unstated")

# Aliases job boards and postings commonly use for "on_site", normalised
# before comparison against REMOTE_ARRANGEMENT_VALUES.
_ON_SITE_ALIASES = frozenset({"onsite", "on-site", "office"})

# Free-text language requirement values that mean "no requirement stated".
_NO_LANGUAGE_VALUES = frozenset({"", "none"})

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


def remote_compatible(profile_remote_model: str | None, arrangement: str) -> bool:
    """Whether a posting's stated ``arrangement`` fits ``profile_remote_model``.

    A profile of 'remote' accepts only a posting stated (or known to be)
    remote/unstated/"". A profile of 'hybrid' additionally accepts hybrid.
    'on_site', any other value, and an empty/None profile accept any
    arrangement — there is nothing to conflict with.
    """
    if not profile_remote_model:
        return True
    allowed = _COMPATIBLE_ARRANGEMENTS.get(profile_remote_model)
    if allowed is None:
        return True
    return arrangement in allowed


def language_compatible(working_language: str | None, requirement: str) -> bool:
    """Whether a posting's stated language ``requirement`` fits the profile.

    True when the profile has no working language, the posting states no
    requirement, or the two match exactly (case/whitespace-insensitively,
    via the same normalisation as ``validate_language_requirement``). No
    fuzzy matching: "German" and "Deutsch" are not considered the same.
    """
    if not working_language or not requirement:
        return True
    return validate_language_requirement(working_language) == validate_language_requirement(
        requirement
    )


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
