"""Guardrail-truthful cover-letter generation.

The letter is produced as paragraphs of connective prose, each tagging the
factual claims it makes. Only those factual claims are validated by the guardrail
against the truth store; connective narrative is free. If any claim is
unverifiable the letter is blocked and nothing is returned as text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from guardrail import Scope, validate
from providers.base import LLMProvider
from truth.model import Truth
from truth.store import data_dir

import prompts


def _letter_draft_path() -> Path:
    """Where the last generated letter's paragraphs are cached.

    Persisting them lets an approve/decline round-trip re-validate the EXACT
    letter the user reviewed instead of a fresh LLM generation whose reworded
    claims would no longer match the ids the UI sent back.
    """
    return data_dir() / "cover_letter_draft.json"


def save_letter_draft(paragraphs: list[dict]) -> Path:
    """Cache the generated paragraphs so approvals can round-trip by claim id."""
    p = _letter_draft_path()
    p.write_text(json.dumps(paragraphs, indent=2), encoding="utf-8")
    return p


def load_letter_draft() -> list[dict] | None:
    """Reload the last generated letter's paragraphs, or None if absent."""
    p = _letter_draft_path()
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))

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


# Stable scope id for the letter's single validation scope. Callers derive a
# blocked-claim's id from (LETTER_SCOPE_ID, claim text), so this must not change
# without also updating the API's _claim_id round-trip.
LETTER_SCOPE_ID = "letter"


def build_letter(
    posting: str,
    tone: str,
    length: str,
    truth: Truth,
    provider: LLMProvider,
    approved_texts: set[str] | None = None,
    denied_texts: set[str] | None = None,
    paragraphs: list[dict] | None = None,
) -> dict:
    """Generate a guardrailed cover letter.

    Returns {blocked, unverifiable, blocked_claims, text}; text is "" when
    blocked. ``approved_texts`` are claim strings the user has approved for THIS
    generation only — they are added to the guardrail's allowed set (never
    written to truth), mirroring the CV render approval flow. ``denied_texts``
    are dropped from the letter entirely so they can't ship.

    ``paragraphs`` short-circuits the LLM: pass the cached paragraphs from a
    prior attempt (see load_letter_draft) so an approve/decline round-trip
    re-validates the SAME letter the user reviewed. When omitted, the letter is
    generated fresh and cached for the next round-trip.
    """
    if paragraphs is None:
        paragraphs = _generate_paragraphs(posting, tone, length, truth, provider)
        save_letter_draft(paragraphs)

    scope = _letter_scope(paragraphs, truth, approved_texts or set(), denied_texts or set())
    check = validate([scope])
    if not check.ok:
        return {
            "blocked": True,
            "unverifiable": check.unverifiable,
            "blocked_claims": check.blocked_claims,
            "text": "",
        }

    text = "\n\n".join(p.get("text", "").strip() for p in paragraphs if p.get("text", "").strip())
    return {"blocked": False, "unverifiable": [], "blocked_claims": [], "text": text}


def _generate_paragraphs(
    posting: str, tone: str, length: str, truth: Truth, provider: LLMProvider
) -> list[dict]:
    """Ask the provider for the letter's paragraphs + tagged factual claims."""
    user = f"POSTING:\n{posting}\n\nCANDIDATE FACTS:\n{prompts.cover_letter_facts_block(truth)}"
    result = provider.extract_json(
        prompts.cover_letter_system(tone, length),
        [{"role": "user", "content": user}],
        _SCHEMA,
    )
    return result.get("paragraphs", []) if isinstance(result, dict) else []


def _letter_scope(
    paragraphs: list[dict],
    truth: Truth,
    approved_texts: set[str],
    denied_texts: set[str],
) -> Scope:
    """The single validation scope for the letter's factual claims.

    Approved claim texts are appended to `allowed` (traceable for THIS
    generation only, no truth write); denied claims are excluded from `texts`.
    """
    claims = [
        c
        for para in paragraphs
        for c in para.get("claims", [])
        if c and c not in denied_texts
    ]
    allowed = _all_values(truth) + [t for t in approved_texts if t]
    return Scope(id=LETTER_SCOPE_ID, texts=claims, allowed=allowed)
