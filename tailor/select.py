"""Select, reorder, and rephrase truth for a posting — structured by experience.

The provider picks which experiences and bullets are most relevant and lightly
rephrases the bullets, referencing everything BY ID. This is the enforcement
point of the truthfulness invariant on the tailoring side:

- an experience id that isn't real is dropped;
- a bullet id that doesn't belong to that same experience is dropped;
- role/company/dates (and education, skills) are copied VERBATIM from truth —
  only bullets are rephrased — so headers can never drift.

Anything the posting wants that isn't here resurfaces as an Inference.
"""

from __future__ import annotations

from typing import Any

from providers.base import LLMProvider
from truth.model import Truth

import prompts

from .model import DraftEducation, DraftExperience

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "experiences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "text": {"type": "string"},
                            },
                            "required": ["id", "text"],
                        },
                    },
                },
                "required": ["id", "bullets"],
            },
        },
        "skills": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["experiences", "skills"],
}

def _dates(start: str, end: str) -> str:
    """Format a date range with a spaced en-dash so it tokenizes to separate
    year tokens for the guardrail (a plain hyphen would read as one token)."""
    start, end = start.strip(), end.strip()
    if start and end:
        return f"{start} – {end}"
    return start or end


def select_and_rephrase(
    posting: str, keywords: list[str], truth: Truth, provider: LLMProvider
) -> tuple[list[DraftExperience], list[DraftEducation], list[str]]:
    """Return (experiences, education, skills) for the tailored draft.

    Education is always carried verbatim. Falls back to all truth (verbatim) if
    the provider returns nothing usable.
    """
    education = [
        DraftEducation(source_id=ed.id, degree=ed.degree, school=ed.school, dates=_dates(ed.start, ed.end))
        for ed in truth.education
    ]
    if truth.is_empty():
        return [], education, []

    exp_by_id = {e.id: e for e in truth.experiences}
    skill_by_id = {s.id: s for s in truth.skills}

    user = (
        f"POSTING:\n{posting}\n\n"
        f"KEYWORDS: {', '.join(keywords)}\n\n"
        f"{prompts.select_truth_block(truth)}"
    )
    result = provider.extract_json(
        prompts.select_system(), [{"role": "user", "content": user}], _SCHEMA
    )

    draft_exps: list[DraftExperience] = []
    selected_skill_ids: list[str] = []
    if isinstance(result, dict):
        for row in result.get("experiences", []) or []:
            te = exp_by_id.get(str(row.get("id", "")).strip())
            if te is None:
                continue  # invariant: unknown experience id
            bl_by_id = {b.id: b for b in te.bullets}
            bullets: list[str] = []
            for br in row.get("bullets", []) or []:
                tb = bl_by_id.get(str(br.get("id", "")).strip())
                if tb is None:
                    continue  # invariant: bullet must belong to THIS experience
                bullets.append(str(br.get("text", "")).strip() or tb.value)
            draft_exps.append(
                DraftExperience(
                    source_id=te.id, role=te.role, company=te.company,
                    dates=_dates(te.start, te.end), bullets=bullets,
                )
            )
        selected_skill_ids = [str(x).strip() for x in result.get("skills", []) or []]

    skills = [skill_by_id[sid].value for sid in selected_skill_ids if sid in skill_by_id]

    # Deterministic fallback: verbatim truth in original order.
    if not draft_exps:
        draft_exps = [
            DraftExperience(
                source_id=e.id, role=e.role, company=e.company,
                dates=_dates(e.start, e.end), bullets=[b.value for b in e.bullets],
            )
            for e in truth.experiences
        ]
    if not skills:
        skills = [s.value for s in truth.skills]

    return draft_exps, education, skills
