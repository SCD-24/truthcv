"""Guardrail-truthful cover-letter generation.

The letter is produced as paragraphs of connective prose, each tagging the
factual claims it makes. Only those factual claims are validated by the guardrail
against the truth store; connective narrative is free. If any claim is
unverifiable the letter is blocked and nothing is returned as text.
"""

from __future__ import annotations

from typing import Any

from guardrail import Scope, validate
from providers.base import LLMProvider
from truth.model import Truth

import prompts

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "claims": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text"],
            },
        }
    },
    "required": ["paragraphs"],
}


def _all_values(truth: Truth) -> list[str]:
    """Every factual value in the truth — the letter may reference any of them
    (a cover letter weaves the whole career, so validation is global here)."""
    vals: list[str] = []
    for e in truth.experiences:
        vals += [e.role, e.company, e.start, e.end]
        vals += [b.value for b in e.bullets]
    for ed in truth.education:
        vals += [ed.degree, ed.school, ed.start, ed.end]
    vals += [s.value for s in truth.skills]
    return [v for v in vals if v]


def build_letter(
    posting: str,
    tone: str,
    length: str,
    truth: Truth,
    provider: LLMProvider,
) -> dict:
    """Return {blocked, unverifiable, text}. text is "" when blocked."""
    user = f"POSTING:\n{posting}\n\nCANDIDATE FACTS:\n{prompts.cover_letter_facts_block(truth)}"
    result = provider.extract_json(
        prompts.cover_letter_system(tone, length),
        [{"role": "user", "content": user}],
        _SCHEMA,
    )
    paragraphs = result.get("paragraphs", []) if isinstance(result, dict) else []

    claims = [c for para in paragraphs for c in para.get("claims", []) if c]
    check = validate([Scope(texts=claims, allowed=_all_values(truth))])
    if not check.ok:
        return {"blocked": True, "unverifiable": check.unverifiable, "text": ""}

    text = "\n\n".join(p.get("text", "").strip() for p in paragraphs if p.get("text", "").strip())
    return {"blocked": False, "unverifiable": [], "text": text}
