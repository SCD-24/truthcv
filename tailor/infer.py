"""Detect claims the tailoring wants to add that are NOT yet in the truth store.

Given the posting keywords and the current truth, ask the provider which relevant
qualifications the posting expects that the truth does NOT already cover — and,
for each, which experience it best relates to. Each becomes an Inference the user
must confirm; an approved one is written back as a user-confirmed bullet on that
experience. Nothing here is written to truth — it only proposes.
"""

from __future__ import annotations

from typing import Any

from providers.base import LLMProvider
from truth.model import Truth

import prompts

from .model import Inference

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "inferences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "rationale": {"type": "string"},
                    "experienceId": {"type": "string"},
                },
                "required": ["claim"],
            },
        }
    },
    "required": ["inferences"],
}

def detect_inferences(
    keywords: list[str], truth: Truth, provider: LLMProvider
) -> list[Inference]:
    """Return Inferences (each tagged with a target experience id) for claims not
    already in truth."""
    existing = {b.value.strip().lower() for e in truth.experiences for b in e.bullets}
    existing |= {s.value.strip().lower() for s in truth.skills}
    exp_ids = {e.id for e in truth.experiences}
    default_exp = truth.experiences[0].id if truth.experiences else ""

    user = f"KEYWORDS: {', '.join(keywords)}\n\n{prompts.infer_truth_block(truth)}"
    result = provider.extract_json(
        prompts.infer_system(), [{"role": "user", "content": user}], _SCHEMA
    )
    rows = result.get("inferences", []) if isinstance(result, dict) else []

    out: list[Inference] = []
    seen: set[str] = set()
    for i, row in enumerate(rows):
        claim = str(row.get("claim", "")).strip()
        low = claim.lower()
        if not claim or low in existing or low in seen:
            continue
        seen.add(low)
        eid = str(row.get("experienceId", "")).strip()
        if eid not in exp_ids:
            eid = default_exp
        out.append(
            Inference(
                id=f"inf-{i + 1}",
                claim=claim,
                rationale=str(row.get("rationale", "")).strip(),
                experience_id=eid,
            )
        )
    return out
