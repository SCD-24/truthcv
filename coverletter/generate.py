"""Guardrail-truthful cover-letter generation.

The letter is produced as paragraphs of connective prose, each tagging the
factual claims it makes. Only those factual claims are validated by the guardrail
against the truth store; connective narrative is free. If any claim is
unverifiable the letter is blocked and nothing is returned as text.
"""

from __future__ import annotations

from typing import Any

from guardrail import validate
from providers.base import LLMProvider
from tailor.style import LETTER_STYLE
from truth.model import TruthEntry

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


def _system(tone: str, length: str) -> str:
    return (
        f"Write a {tone.lower()} cover letter of {length.lower()} length. For every "
        "sentence that states a FACT about the candidate (employer, title, date, "
        "metric, skill, achievement), list that fact verbatim in 'claims'. Do NOT "
        "invent any fact not supported by the candidate's truth. Connective/"
        "narrative sentences need no claims." + LETTER_STYLE
    )


def build_letter(
    posting: str,
    tone: str,
    length: str,
    truth: list[TruthEntry],
    provider: LLMProvider,
) -> dict:
    """Return {blocked, unverifiable, text}. text is "" when blocked."""
    user = (
        f"POSTING:\n{posting}\n\nCANDIDATE FACTS:\n"
        + "\n".join(f"- {e.value}" for e in truth)
    )
    result = provider.extract_json(_system(tone, length), [{"role": "user", "content": user}], _SCHEMA)
    paragraphs = result.get("paragraphs", []) if isinstance(result, dict) else []

    claims = [c for para in paragraphs for c in para.get("claims", []) if c]
    check = validate(claims, [e.value for e in truth])
    if not check.ok:
        return {"blocked": True, "unverifiable": check.unverifiable, "text": ""}

    text = "\n\n".join(p.get("text", "").strip() for p in paragraphs if p.get("text", "").strip())
    return {"blocked": False, "unverifiable": [], "text": text}
