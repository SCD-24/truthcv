"""The prompt store: the single home for every LLM prompt in TruthCV.

Why a store, not inline prompts: prompt text is a cross-cutting asset that is
edited, reviewed, and tuned independently of the code that assembles a call.
Keeping all system prompts, user-message text builders, and the shared style
fragments here means there is exactly one place to read or change what the model
is told — while the JSON schemas (structural I/O contracts) stay with their
feature modules, and nothing the model returns is trusted until it passes the
truth store and the deterministic guardrail.

Each prompt is served as a function so callers never reach past this API to a
raw constant; style fragments live in ``prompts.style`` and are re-exported.
"""

from __future__ import annotations

from .style import CV_STYLE, LETTER_STYLE
from .truth import extract_system
from .tailor import (
    keywords_system,
    infer_system,
    infer_truth_block,
    select_system,
    select_truth_block,
)
from .coverletter import cover_letter_system, cover_letter_facts_block

__all__ = [
    "CV_STYLE",
    "LETTER_STYLE",
    "extract_system",
    "keywords_system",
    "infer_system",
    "infer_truth_block",
    "select_system",
    "select_truth_block",
    "cover_letter_system",
    "cover_letter_facts_block",
]
