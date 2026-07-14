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


def extract_keywords(posting: str, provider: LLMProvider) -> list[str]:
    """Return an ordered, de-duplicated list of posting keywords."""
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
        if kw and low not in seen:
            seen.add(low)
            out.append(kw)
    return out
