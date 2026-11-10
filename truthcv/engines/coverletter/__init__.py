"""Cover-letter generation: guardrail-truthful, claims + connective glue."""

from .generate import LETTER_SCOPE_ID, build_letter, load_letter_draft, save_letter_draft

__all__ = ["build_letter", "load_letter_draft", "save_letter_draft", "LETTER_SCOPE_ID"]
