"""Operator-route adapter over services/letters.py's operator letter workflow.

The workflow itself lives in services/letters.py, which never builds a
provider; this wrapper supplies `get_provider` as the provider factory. It
looks `get_provider` up as a module global at call time, so tests patch
`agenttools.letter_operator.get_provider`.

Kept only because api/routes.py still imports from here; a later wave deletes
this module once that importer is repointed.
"""

from __future__ import annotations

from providers import get_provider
from services import letters as _letters


def generate_cover_letter_for_operator(
    posting: str,
    length: str,
    approved_texts: list[str] | None = None,
    denied_texts: list[str] | None = None,
    paragraphs: list[dict] | None = None,
    provider=None,
    company: str | None = None,
    preset_id: str | None = None,
) -> dict:
    """Generate an operator letter, building the provider via `get_provider`.

    Same contract as services.letters.generate_cover_letter_for_operator; this
    only injects the provider factory the service must not construct itself.
    """
    return _letters.generate_cover_letter_for_operator(
        posting,
        length,
        approved_texts=approved_texts,
        denied_texts=denied_texts,
        paragraphs=paragraphs,
        provider=provider,
        company=company,
        preset_id=preset_id,
        provider_factory=get_provider,
    )


__all__ = ["generate_cover_letter_for_operator"]
