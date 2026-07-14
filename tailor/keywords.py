"""Extract targeting keywords from a job posting."""

from __future__ import annotations

from typing import Any

from providers.base import LLMProvider

import prompts

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"keywords": {"type": "array", "items": {"type": "string"}}},
    "required": ["keywords"],
}

# Work-arrangement / location markers — never screenable skills, so a keyword
# built around them ('Remote in Germany') pollutes the ATS review.
_ARRANGEMENT_WORDS = frozenset(
    {"remote", "hybrid", "onsite", "on-site", "relocation", "relocate", "based in"}
)
# Seniority prefixes that mark a bare job title ('Senior Data Engineer') rather
# than a skill. Matched only at the start of a token to stay conservative.
_SENIORITY_PREFIXES = (
    "senior ",
    "junior ",
    "lead ",
    "principal ",
    "staff ",
    "mid-level ",
    "entry-level ",
)


def _is_junk_token(keyword: str) -> bool:
    """True when a keyword is a location/arrangement/title, not a real skill.

    Deterministic safety net behind the tightened extraction prompt: even if the
    model slips a non-skill through, it never reaches the ATS keyword review.
    Conservative by design — only clear location/arrangement/title shapes match,
    so genuine skills are never dropped.
    """
    low = keyword.lower()
    if any(word in low for word in _ARRANGEMENT_WORDS):
        return True
    return low.startswith(_SENIORITY_PREFIXES)


def extract_keywords(posting: str, provider: LLMProvider) -> list[str]:
    """Return an ordered, de-duplicated list of screenable posting keywords."""
    if not posting or not posting.strip():
        return []
    result = provider.extract_json(
        prompts.keywords_system(), [{"role": "user", "content": posting}], _SCHEMA
    )
    raw = result.get("keywords", []) if isinstance(result, dict) else []
    seen: set[str] = set()
    out: list[str] = []
    for k in raw:
        kw = str(k).strip()
        low = kw.lower()
        if kw and low not in seen and not _is_junk_token(kw):
            seen.add(low)
            out.append(kw)
    return out
