"""Operator-facing cover-letter generation, with generation-scoped approvals.

Unlike agenttools/tools_letter.py (the agent-facing tool surface), this module
is NOT registered anywhere as an agent tool — nothing in agenttools/mcp_app.py
or agenttools/server.py references it. It exists solely for the operator HTTP
route (api/routes.py's POST /screenings/{id}/letter) to call directly, where a
human is making an approval decision in the moment. An unattended agent must
never get this lever: if it could pass approved claim texts it would be
self-approving its own inferences, which is exactly what the registered
`generate_cover_letter` tool forbids by not exposing any such parameter.
"""

from __future__ import annotations

from dataclasses import asdict

from agentconfig.store import is_blocked, load as load_agent_config
from coverletter.generate import _generate_paragraphs, build_letter
from providers import get_provider
from truth.answers import load as load_answers
from truth.store import load as load_truth


def generate_cover_letter_for_operator(
    posting: str,
    tone: str,
    length: str,
    approved_texts: list[str] | None = None,
    denied_texts: list[str] | None = None,
    paragraphs: list[dict] | None = None,
    provider=None,
    company: str | None = None,
    preset_id: str | None = None,
) -> dict:
    """Generate a guardrailed cover letter, honouring operator approvals.

    ``approved_texts`` are claim strings an operator has approved for THIS
    single generation only. They are added to the guardrail's allowed set and
    are NEVER written to truth — the approval widens what may ship in this one
    letter and evaporates when the call returns. This function is deliberately
    NOT registered as an agent tool (see module docstring): only the
    operator-facing HTTP route may call it.

    ``company``, when given, is refused outright if blocklisted in the agent
    config.

    ``preset_id`` (optional) selects a writing style preset; when omitted,
    tone-based selection applies.
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
        approved_texts=set(approved_texts or []),
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
