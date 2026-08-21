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
from truth.store import load as load_truth


def generate_cover_letter(
    posting: str,
    tone: str,
    length: str,
    denied_texts: list[str] | None = None,
    paragraphs: list[dict] | None = None,
    provider=None,
    company: str | None = None,
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
        else _generate_paragraphs(posting, tone, length, truth, provider)
    )
    result = build_letter(
        posting,
        tone,
        length,
        truth,
        provider,
        denied_texts=set(denied_texts or []),
        paragraphs=paras,
    )
    return {
        "text": result["text"],
        "blocked": result["blocked"],
        "blocked_claims": [asdict(c) for c in result["blocked_claims"]],
        "unverifiable": result["unverifiable"],
        "paragraphs": paras,
    }
