"""Tailor Engine: fit the CV to a posting without ever inventing facts.

tailor() returns {keywords, inferences, draft}. The draft is persisted to the
data volume so /api/render can assemble the CV from it, and the inference list is
persisted so /api/confirm-inferences can map approved ids back to their claims
and target experience.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from providers.base import LLMProvider
from truth.model import Truth
from truth.store import data_dir

from .infer import detect_inferences
from .keywords import extract_keywords
from .model import Draft, DraftEducation, DraftExperience, Inference
from .select import select_and_rephrase

__all__ = [
    "Draft",
    "DraftExperience",
    "DraftEducation",
    "Inference",
    "tailor",
    "load_draft",
    "save_draft",
    "claims_for_ids",
    "valid_experience_ids",
]


def _draft_path() -> Path:
    return data_dir() / "draft.json"


def save_draft(draft: Draft) -> Path:
    p = _draft_path()
    p.write_text(json.dumps(draft.to_dict(), indent=2), encoding="utf-8")
    return p


def load_draft() -> Draft | None:
    p = _draft_path()
    if not p.exists():
        return None
    return Draft.from_dict(json.loads(p.read_text(encoding="utf-8")))


def valid_experience_ids() -> set[str]:
    """Experience ids present in the saved draft.

    Lets the confirm route sanity-check a client-supplied (re-targeted)
    experienceId before writing: an unknown id can be dropped to a safe default
    rather than trusted blindly. Empty when no draft is persisted.
    """
    draft = load_draft()
    if draft is None:
        return set()
    return {e.source_id for e in draft.experiences}


def claims_for_ids(approved_ids: list[str]) -> list[tuple[str, str]]:
    """Map approved inference ids to (experience_id, claim) from the saved draft."""
    draft = load_draft()
    if draft is None:
        return []
    wanted = set(approved_ids)
    return [
        (inf.experience_id, inf.claim)
        for inf in draft.inferences
        if inf.id in wanted
    ]


def tailor(posting: str, truth: Truth, provider: LLMProvider) -> dict[str, Any]:
    """Produce keywords, inferences, and a truth-only structured draft; persist it.

    Returns a dict matching the frontend's TailorResult ({keywords, inferences}),
    plus the draft for internal render use.
    """
    keywords = extract_keywords(posting, provider)
    experiences, education, skills = select_and_rephrase(posting, keywords, truth, provider)
    inferences = detect_inferences(keywords, truth, provider)

    draft = Draft(
        experiences=experiences,
        education=education,
        skills=skills,
        keywords=keywords,
        inferences=inferences,
    )
    save_draft(draft)

    return {
        "keywords": keywords,
        "inferences": [i.to_dict() for i in inferences],
        "draft": draft,
    }
