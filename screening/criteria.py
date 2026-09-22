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

# The posting's own stated EOR/PEO requirement. "" means not supplied;
# "unstated" means the agent looked and the posting did not say.
EOR_STATED_VALUES = ("", "yes", "no", "unstated")

# Free-text evidence values (salary/employment-country/role-type) that mean
# "no evidence stated" — the general-purpose analogue of _NO_LANGUAGE_VALUES.
_NO_VALUE_STATED = frozenset(
    {"", "none", "unstated", "not stated", "n/a", "any"}
)

# Multiplier applied to a "k" suffix in free-text salary evidence ("80k").
SALARY_KILO_MULTIPLIER = 1000

# Matches a number in free-text salary evidence: either comma-grouped
# thousands ("80,000") or a plain run of digits ("80"), optionally followed
# by a "k" suffix ("80k").
_SALARY_NUMBER_RE = re.compile(
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(k)?", re.IGNORECASE
)


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


def validate_eor_stated(value: str) -> str:
    """Return the normalized EOR-stated value, or raise ``ValueError`` if unknown.

    Mirrors ``validate_remote_arrangement``'s normalisation (strip/casefold).
    "" means the field was not supplied; "unstated" means the agent looked and
    the posting did not say; "yes"/"no" is the posting's own explicit answer
    to whether an EOR/PEO employer of record is required.
    """
    cleaned = value.strip().casefold() if isinstance(value, str) else ""
    if cleaned not in EOR_STATED_VALUES:
        raise ValueError(
            f"Unknown EOR-stated value {value!r}. Use one of: "
            f"{', '.join(EOR_STATED_VALUES)}."
        )
    return cleaned


def validate_stated_text(value: str) -> str:
    """Return normalized free-text stated evidence, or "" if none is stated.

    Used for salary/employment-country/role-type evidence fields: collapses
    whitespace and casefolds, then maps "unstated"-family spellings (the same
    vocabulary as ``_NO_LANGUAGE_VALUES``/``validate_language_requirement``)
    to "". Never raises: free text is accepted as-is once normalised.
    """
    cleaned = " ".join(value.split()).casefold() if isinstance(value, str) else ""
    if cleaned in _NO_VALUE_STATED:
        return ""
    return cleaned


def _parse_max_salary_amount(stated: str) -> float | None:
    """Return the highest numeric amount found in free-text salary evidence.

    Handles a plain number, comma thousands separators ("80,000"), and a "k"
    suffix ("80k" -> 80 * ``SALARY_KILO_MULTIPLIER``). A range (e.g.
    "€70,000–90,000") yields more than one candidate number; the maximum is
    returned, since a posting's range is only incompatible with a floor when
    even its top figure falls short. Returns None when no number can be parsed.
    """
    amounts = []
    for match in _SALARY_NUMBER_RE.finditer(stated):
        raw_number, kilo_suffix = match.groups()
        amount = float(raw_number.replace(",", ""))
        if kilo_suffix:
            amount *= SALARY_KILO_MULTIPLIER
        amounts.append(amount)
    return max(amounts) if amounts else None


def salary_compatible(salary_floor: int | None, salary_stated: str) -> bool:
    """Whether a posting's stated salary evidence fits a profile's salary_floor.

    Incompatible ONLY when a number can be parsed from ``salary_stated`` and
    its maximum falls below ``salary_floor``. An unset floor, unstated/empty
    evidence, or evidence with no parsable number are all compatible — there
    is nothing to conflict with, or nothing to conflict on.
    """
    if not salary_floor:
        return True
    stated = validate_stated_text(salary_stated)
    if not stated:
        return True
    max_amount = _parse_max_salary_amount(stated)
    if max_amount is None:
        return True
    return max_amount >= salary_floor


def country_compatible(employment_country: str | None, country_stated: str) -> bool:
    """Whether a posting's stated employment country fits the profile's.

    Compares casefolded values, either containing the other (so "Germany"
    matches a stated "Berlin, Germany" and vice versa). An unset profile
    value, or unstated/empty evidence, is always compatible.
    """
    if not employment_country:
        return True
    stated = validate_stated_text(country_stated)
    if not stated:
        return True
    required = employment_country.strip().casefold()
    return required in stated or stated in required


def role_type_compatible(
    rejected_role_types: list[str] | None, role_type_stated: str
) -> bool:
    """Whether a posting's stated role type avoids all of a profile's rejected types.

    Incompatible when the (casefolded) stated role type matches any rejected
    entry as a substring in either direction. No rejected types, or
    unstated/empty evidence, is always compatible.
    """
    if not rejected_role_types:
        return True
    stated = validate_stated_text(role_type_stated)
    if not stated:
        return True
    for rejected in rejected_role_types:
        rejected_norm = rejected.strip().casefold() if isinstance(rejected, str) else ""
        if rejected_norm and (rejected_norm in stated or stated in rejected_norm):
            return False
    return True


def eor_compatible(eor_allowed: bool | None, eor_stated: str) -> bool:
    """Whether a posting's stated EOR evidence fits a profile's eor_allowed.

    Incompatible ONLY when the profile disallows EOR/PEO employment
    (``eor_allowed is False``) and the posting explicitly states one is
    required (``eor_stated == "yes"``). Any other combination — an unset
    profile, an allowing profile, or the posting stating "no"/"unstated"/""
    — is compatible.
    """
    return not (eor_allowed is False and eor_stated == "yes")


def evaluate_hard_requirements(profile, evidence: dict) -> tuple[str, str]:
    """Check a posting's evidence against all six of a profile's hard requirements.

    Runs remote arrangement, working language, salary_floor,
    employment_country, rejected_role_types, and eor_allowed in that fixed
    order and returns on the first failure as ``(failing_criterion, reason)``,
    matching ``evaluate``'s contract; ``("", "")`` means the posting is
    compatible with every requirement the profile actually states. ``evidence``
    holds the screening's own evidence fields: remote_arrangement,
    language_requirement, salary_stated, employment_country_stated,
    role_type_stated, eor_stated.
    """
    remote = evidence.get("remote_arrangement", "")
    language = evidence.get("language_requirement", "")
    salary = evidence.get("salary_stated", "")
    country = evidence.get("employment_country_stated", "")
    role_type = evidence.get("role_type_stated", "")
    # The one evidence value not funnelled through validate_stated_text:
    # normalise casing here so a caller-supplied "Yes" behaves like "yes".
    eor = (evidence.get("eor_stated") or "").strip().casefold()

    checks = (
        ("remote_model", remote_compatible(profile.remote_model, remote),
         f"Profile requires {profile.remote_model!r} but the posting states "
         f"remote arrangement {remote!r}."),
        ("working_language", language_compatible(profile.working_language, language),
         f"Profile working language is {profile.working_language!r} but the "
         f"posting explicitly requires {language!r}."),
        ("salary_floor", salary_compatible(profile.salary_floor, salary),
         f"Profile requires a salary floor of {profile.salary_floor!r} but "
         f"the posting states {salary!r}."),
        ("employment_country", country_compatible(profile.employment_country, country),
         f"Profile requires employment country {profile.employment_country!r} "
         f"but the posting states {country!r}."),
        ("rejected_role_types", role_type_compatible(profile.rejected_role_types, role_type),
         f"Profile rejects role types {profile.rejected_role_types!r} but the "
         f"posting states role type {role_type!r}."),
        ("eor_allowed", eor_compatible(profile.eor_allowed, eor),
         f"Profile requires eor_allowed={profile.eor_allowed!r} but the "
         f"posting states EOR {eor!r}."),
    )
    for criterion, compatible, reason in checks:
        if not compatible:
            return (criterion, reason)
    return ("", "")
