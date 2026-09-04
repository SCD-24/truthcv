"""Per-application cover-letter tool for the agent tool surface.

Unlike the wizard's POST /api/cover-letter route, this tool reads and writes
NOTHING global: the posting, tone, length, and any previously generated
paragraphs all arrive as arguments, and the generated letter is returned to the
caller rather than cached on disk. N unattended applications can call this
concurrently without clobbering each other's state.
"""

from __future__ import annotations

from dataclasses import asdict

# The private helper is used (instead of letting build_letter generate its own
# paragraphs) because build_letter's lazy path calls save_letter_draft(paragraphs),
# which writes the single global data_dir()/"cover_letter_draft.json". Passing
# paragraphs= unconditionally below is what keeps build_letter from writing that
# shared file, so each application's draft lives only in this call's return value.
from agentconfig.store import is_blocked, load as load_agent_config
from coverletter.generate import _generate_paragraphs, build_letter
from providers import get_provider
from truth.answers import load as load_answers
from truth.store import load as load_truth


def generate_cover_letter(
    posting: str,
    tone: str,
    length: str,
    denied_texts: list[str] | None = None,
    paragraphs: list[dict] | None = None,
    provider=None,
    company: str | None = None,
    preset_id: str | None = None,
) -> dict:
    """Generate (or re-validate) a guardrailed cover letter for one application.

    All per-application state — the posting, tone, length, any previously
    generated ``paragraphs``, and any ``denied_texts`` to excise — is passed in
    and returned; nothing is read from or written to a shared file. There is no
    approval parameter: this tool cannot be used to self-approve an inference,
    only to generate a fresh letter or retry excising denied claims from an
    already-generated one (via ``paragraphs``, avoiding a second LLM call).

    ``company``, when given, is refused outright if blocklisted in the agent
    config.

    ``preset_id`` (optional) selects a writing style preset; when omitted,
    tone-based selection applies. The tool schema, inferred from this
    signature by agenttools/mcp_app.py, automatically exposes presetId as a
    schema argument.
    """
    if company is not None and is_blocked(load_agent_config(), company):
        return {
            "text": "",
            "blocked": True,
            "blocked_claims": [],
            "unverifiable": [],
            "paragraphs": [],
            "blocked_reason": "company_blocked",
        }
    if provider is None:
        provider = get_provider("cover_letter")
    truth = load_truth()
    paras = (
        paragraphs
        if paragraphs is not None
        else _generate_paragraphs(
            posting, tone, length, truth, provider, preset_id=preset_id
        )
    )
    result = build_letter(
        posting,
        tone,
        length,
        truth,
        provider,
        denied_texts=set(denied_texts or []),
        paragraphs=paras,
        # Same signature the wizard produces. Only the name is taken from the
        # answers store here — the answers are deliberately NOT passed as
        # guardrail claim sources on this path, which would widen what the
        # unattended agent is allowed to assert.
        sign_off_name=load_answers().name or truth.profile.name,
        preset_id=preset_id,
    )
    return {
        "text": result["text"],
        "blocked": result["blocked"],
        "blocked_claims": [asdict(c) for c in result["blocked_claims"]],
        "unverifiable": result["unverifiable"],
        "paragraphs": paras,
    }
