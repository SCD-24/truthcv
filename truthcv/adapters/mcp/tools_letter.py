"""Per-application cover-letter tool for the agent tool surface.

Unlike the wizard's POST /api/cover-letter route, this tool reads and writes
NOTHING global: the posting, length, writing-style preset, and any previously generated
paragraphs all arrive as arguments, and the generated letter is returned to the
caller rather than cached on disk. N unattended applications can call this
concurrently without clobbering each other's state.
"""

from __future__ import annotations

from truthcv.integrations.providers import get_provider
from truthcv.services.letters import generate_letter


def generate_cover_letter(
    posting: str,
    length: str,
    denied_texts: list[str] | None = None,
    paragraphs: list[dict] | None = None,
    provider=None,
    company: str | None = None,
    preset_id: str | None = None,
) -> dict:
    """Generate (or re-validate) a guardrailed cover letter for one application.

    All per-application state — the posting, length, any previously
    generated ``paragraphs``, and any ``denied_texts`` to excise — is passed in
    and returned; nothing is read from or written to a shared file. There is no
    approval parameter: this tool cannot be used to self-approve an inference,
    only to generate a fresh letter or retry excising denied claims from an
    already-generated one (via ``paragraphs``, avoiding a second LLM call).

    ``company``, when given, is refused outright if blocklisted in the agent
    config.

    ``preset_id`` (optional) selects a writing style preset; when omitted, the
    user's default writing-style preset applies. The tool schema, inferred
    from this signature by agenttools/mcp_app.py, automatically exposes
    presetId as a schema argument.
    """
    return generate_letter(
        posting,
        length,
        denied_texts=denied_texts,
        paragraphs=paragraphs,
        provider=provider,
        provider_factory=get_provider,
        company=company,
        preset_id=preset_id,
    )
