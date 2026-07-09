"""Select, reorder, and rephrase truth entries for a posting — by id only.

The provider is asked to pick and rephrase entries REFERENCED BY ID. This module
is the enforcement point of the truthfulness invariant on the tailoring side:
any proposed line whose id is not a real truth entry is dropped here (it may
resurface as an Inference via tailor/infer.py). Every surviving DraftLine
carries the source truth id so the guardrail and renderer can trace provenance.
"""

from __future__ import annotations

from typing import Any

from providers.base import LLMProvider
from truth.model import TruthEntry

from .model import DraftLine
from .style import CV_STYLE

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sourceId": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["sourceId", "text"],
            },
        }
    },
    "required": ["lines"],
}

_SYSTEM = (
    "You tailor a CV to a job posting. You are given a fixed list of truth "
    "entries (each with an id). Select and reorder the entries most relevant to "
    "the posting and lightly rephrase each for impact. RULES: (1) reference ONLY "
    "the provided ids via sourceId; (2) NEVER invent a new fact, number, employer, "
    "date, or achievement not present in the referenced entry; (3) rephrasing must "
    "not add information. Return the ordered lines." + CV_STYLE
)


def _truth_block(truth: list[TruthEntry]) -> str:
    return "\n".join(f"[{e.id}] ({e.kind}) {e.value}" for e in truth)


def select_and_rephrase(
    posting: str, keywords: list[str], truth: list[TruthEntry], provider: LLMProvider
) -> list[DraftLine]:
    """Return ordered DraftLines, each referencing a REAL truth id.

    Lines referencing unknown ids are dropped. Falls back to including all truth
    entries verbatim if the provider returns nothing usable.
    """
    by_id = {e.id: e for e in truth}
    if not by_id:
        return []

    user = (
        f"POSTING:\n{posting}\n\n"
        f"KEYWORDS: {', '.join(keywords)}\n\n"
        f"TRUTH ENTRIES:\n{_truth_block(truth)}"
    )
    result = provider.extract_json(_SYSTEM, [{"role": "user", "content": user}], _SCHEMA)
    rows = result.get("lines", []) if isinstance(result, dict) else []

    lines: list[DraftLine] = []
    used: set[str] = set()
    for row in rows:
        sid = str(row.get("sourceId", "")).strip()
        entry = by_id.get(sid)
        if entry is None:
            continue  # invariant: drop lines with no real truth id
        text = str(row.get("text", "")).strip() or entry.value
        lines.append(DraftLine(source_id=sid, kind=entry.kind, text=text))
        used.add(sid)

    if not lines:
        # Deterministic fallback: verbatim truth, original order.
        lines = [
            DraftLine(source_id=e.id, kind=e.kind, text=e.value) for e in truth
        ]
    return lines
