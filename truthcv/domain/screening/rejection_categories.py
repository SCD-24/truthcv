"""Canonical rejection categories for a screening's ``failing_criterion``.

The agent writes free-text criteria ("1. Fully remote", "Employment country:
Germany"). This module maps any such text onto a small closed set of keys so
the Screenings page can group and count rejections.
"""

from __future__ import annotations

import re

REJECTION_CATEGORIES = (
    "remote_model",
    "working_language",
    "salary_floor",
    "employment_country",
    "rejected_role_types",
    "eor_allowed",
    "role_fit",
    "posting_age",
    "cooldown",
    "other",
)

# Ordered (category, pattern) rules on casefolded text; first match wins.
_RULES = (
    ("cooldown", re.compile(r"cooldown")),
    ("eor_allowed", re.compile(r"\b(eor|peo)\b|employer of record")),
    ("posting_age", re.compile(r"posting age|posted|stale|too old|freshness")),
    ("salary_floor", re.compile(r"salary|\bpay\b|compensation|\brates?\b")),
    ("remote_model", re.compile(r"remote|hybrid|on-site|onsite|\boffices?\b")),
    ("working_language", re.compile(r"language|\bgerman\b|english|fluent")),
    (
        "rejected_role_types",
        re.compile(
            r"role type|contract|agency|freelance|temporary|part-time|internship"
        ),
    ),
    (
        "employment_country",
        re.compile(r"country|location|relocat|visa|residen|based in"),
    ),
    (
        "role_fit",
        re.compile(
            r"role|seniority|title|skill|experience|stack|\bfit\b|entity|domain"
        ),
    ),
)


def normalize_failing_criterion(raw: str) -> str:
    """Map free text to a canonical rejection category; never raises.

    ``None``/blank gives ``''``. Text that already is a canonical key is
    returned unchanged (idempotent); otherwise the first matching keyword rule
    wins, falling back to ``'other'``.
    """
    text = str(raw or "").casefold()
    if not text.strip():
        return ""
    key = re.sub(r"[\s\-:]+", "_", text).strip("_")
    if key in REJECTION_CATEGORIES:
        return key
    for category, pattern in _RULES:
        if pattern.search(text):
            return category
    return "other"
