"""Per-application cover-letter tool for the agent tool surface.

Unlike the wizard's POST /api/cover-letter route, this tool reads and writes
NOTHING global: the posting, tone, length, and any previously generated
paragraphs all arrive as arguments, and the generated letter is returned to the
caller rather than cached on disk. N unattended applications can call this
concurrently without clobbering each other's state.

The one file it does write is the uploadable PDF of the letter it just
generated (agenttools/letter_files.py), named by a digest of that letter's own
text — so concurrent calls still cannot clobber one another, and a repeat call
producing the same letter overwrites it with itself.
"""

from __future__ import annotations

from dataclasses import asdict

# The private helper is used (instead of letting build_letter generate its own
# paragraphs) because build_letter's lazy path calls save_letter_draft(paragraphs),
# which writes the single global data_dir()/"cover_letter_draft.json". Passing
# paragraphs= unconditionally below is what keeps build_letter from writing that
# shared file, so each application's draft lives only in this call's return value.
from agentconfig.store import is_blocked, load as load_agent_config
from agenttools.letter_files import NO_FILE, render_generated_letter
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

    A letter that passed the guardrail is also rendered to a PDF on the data
    volume, and the returned ``letter_path`` is where the browser container can
    upload it from — most ATS forms take the letter as a second upload rather
    than as a textarea. A blocked letter is never rendered: the file would be
    an upload of text the guardrail refused. ``letter_path`` is None when no
    rendering backend is installed, which means the letter exists only as
    ``text`` — it is not an error.
    """
    if company is not None and is_blocked(load_agent_config(), company):
        return {
            "text": "",
            "blocked": True,
            "blocked_claims": [],
            "unverifiable": [],
            "paragraphs": [],
            "blocked_reason": "company_blocked",
            "letter_asset_id": None,
            "letter_path": None,
            "letter_download_url": None,
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
        # Same signature the wizard produces. Only the name is taken from the
        # answers store here — the answers are deliberately NOT passed as
        # guardrail claim sources on this path, which would widen what the
        # unattended agent is allowed to assert.
        sign_off_name=load_answers().name or truth.profile.name,
    )
    letter_file = (
        dict(NO_FILE) if result["blocked"] else render_generated_letter(result["text"])
    )
    return {
        "text": result["text"],
        "blocked": result["blocked"],
        "blocked_claims": [asdict(c) for c in result["blocked_claims"]],
        "unverifiable": result["unverifiable"],
        "paragraphs": paras,
        "letter_asset_id": letter_file["asset_id"],
        "letter_path": letter_file["path"],
        "letter_download_url": letter_file["download_url"],
    }
