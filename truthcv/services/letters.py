"""Cover-letter workflow for one application: generation and the letter file.

Two callers share generation here. The agent tool surface
(truthcv/adapters/mcp/tools_letter.py) reads and writes NOTHING global: the posting,
length, writing-style preset, and any previously generated paragraphs all
arrive as arguments, and the generated letter is returned to the caller rather
than cached on disk, so N unattended applications can call it concurrently
without clobbering each other's state. The operator HTTP route
(truthcv/adapters/http/routes.py's POST /screenings/{id}/letter) additionally passes
generation-scoped approvals through `generate_cover_letter_for_operator`.

The provider comes from the caller: either a ready ``provider`` or a
``provider_factory`` called with ``"cover_letter"`` when none is given. This
module never constructs one itself. `load_truth` is looked up as a module
global at call time, so tests patch it on this module.

The letter as a *file*, for the tool that hands the agent something to upload.

Most ATS forms take the cover letter as an upload rather than a textarea, and
the browser container can only upload a path that exists on the shared data
volume. So `get_approved_applications` — the one tool that carries letter text
the operator has approved — renders that exact text to a PDF here and returns
its path alongside it.

Only that path renders. `generate_cover_letter` deliberately does NOT: it
accepts a caller-supplied `paragraphs` argument (that is its documented retry
route), and the guardrail validates each paragraph's declared `claims`, never
its prose. Rendering there would let the agent turn a paragraph carrying an
empty claims list into a signed, letterheaded PDF the guardrail never checked —
a bypass in the one direction that matters, because a document reaches an
employer looking vouched for. A letter generated in-run therefore reaches the
form as text only. The operator's approval, between runs, is what turns a
letter into a file.

Files are content-addressed: the name carries a digest of the text it renders,
so a file that exists is a file whose contents are known, and an edited letter
renders to a different name rather than overwriting a good file with a bad one.
There is no timestamp comparison anywhere here, on purpose. The digest covers
the header as well as the prose, so a profile edit invalidates the render the
same way a rewrite does. An edit's predecessor is swept once its replacement is
on disk, so one screening keeps one finished file — a `.part` left by a process
killed between rendering and moving is swept when the draft is deleted.

Every rendering function is best-effort. When no rendering backend is installed
— or any part of rendering fails — the returned path is None, which means "this
letter exists only as text", never an error. A read of the approved queue must
not be able to fail because a PDF could not be produced.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

# The private helper is used (instead of letting build_letter generate its own
# paragraphs) because build_letter's lazy path calls save_letter_draft(paragraphs),
# which writes the single global data_dir()/"cover_letter_draft.json". Passing
# paragraphs= unconditionally below is what keeps build_letter from writing that
# shared file, so each application's draft lives only in this call's return value.
from truthcv.domain.agentconfig.store import is_blocked, load as load_agent_config
from truthcv.engines.coverletter.generate import _generate_paragraphs, build_letter
from truthcv.engines.coverletter.store import pdf_filename, pdf_path, prune_pdfs
from truthcv.domain.truth.answers import load as load_answers
from truthcv.domain.truth.store import load as load_truth


def generate_letter(
    posting: str,
    length: str,
    *,
    approved_texts: list[str] | None = None,
    denied_texts: list[str] | None = None,
    paragraphs: list[dict] | None = None,
    provider=None,
    provider_factory=None,
    company: str | None = None,
    preset_id: str | None = None,
) -> dict:
    """Generate (or re-validate) a guardrailed cover letter for one application.

    The one generation path behind both the agent tool and the operator route,
    so the blocklist refusal, the paragraph reuse, and the sign-off cannot
    drift between them. Callers differ only in ``approved_texts``: the agent
    tool never passes it (an unattended agent must not self-approve its own
    inferences); the operator route passes claim strings a human approved for
    THIS single generation, which widen the guardrail's allowed set for this
    one letter and are NEVER written to truth.

    All per-application state is passed in and returned; nothing is read from
    or written to a shared file. ``paragraphs``, when given, is re-validated
    instead of calling the LLM again. ``company``, when given, is refused
    outright if blocklisted in the agent config. ``preset_id`` selects a
    writing style preset; when omitted, the user's default preset applies.

    ``provider_factory`` is called with ``"cover_letter"`` only when
    ``provider`` is None, and only after the blocklist check.
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
        provider = provider_factory("cover_letter")
    truth = load_truth()
    paras = (
        paragraphs
        if paragraphs is not None
        else _generate_paragraphs(
            posting, length, truth, provider, preset_id=preset_id
        )
    )
    result = build_letter(
        posting,
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


def generate_cover_letter_for_operator(
    posting: str,
    length: str,
    approved_texts: list[str] | None = None,
    denied_texts: list[str] | None = None,
    paragraphs: list[dict] | None = None,
    provider=None,
    company: str | None = None,
    preset_id: str | None = None,
    *,
    provider_factory=None,
) -> dict:
    """Generate a guardrailed cover letter, honouring operator approvals.

    This function is NOT registered anywhere as an agent tool — nothing in
    truthcv/adapters/mcp/mcp_app.py or truthcv/adapters/mcp/server.py references it. It exists
    solely for the operator HTTP route (truthcv/adapters/http/routes.py's POST
    /screenings/{id}/letter) to call directly, where a human is making an
    approval decision in the moment. An unattended agent must never get this
    lever: if it could pass approved claim texts it would be self-approving its
    own inferences, which is exactly what the registered
    `generate_cover_letter` tool forbids by not exposing any such parameter.

    ``approved_texts`` are claim strings an operator has approved for THIS
    single generation only. They are added to the guardrail's allowed set and
    are NEVER written to truth — the approval widens what may ship in this one
    letter and evaporates when the call returns. This function is deliberately
    NOT registered as an agent tool (see above): only the
    operator-facing HTTP route may call it.

    ``company``, when given, is refused outright if blocklisted in the agent
    config.

    ``preset_id`` (optional) selects a writing style preset; when omitted, the
    operator's default preset applies.

    ``provider_factory`` builds the provider when ``provider`` is None.
    """
    return generate_letter(
        posting,
        length,
        approved_texts=approved_texts,
        denied_texts=denied_texts,
        paragraphs=paragraphs,
        provider=provider,
        provider_factory=provider_factory,
        company=company,
        preset_id=preset_id,
    )


NO_FILE = {"asset_id": None, "path": None, "download_url": None}


def _header_digest(name: str, contact: str) -> str:
    """The header as one string, for the filename digest to cover."""
    return f"{name}\n{contact}"


def _asset(filename: str, path: Path | None) -> dict:
    if path is None:
        return dict(NO_FILE)
    return {
        "asset_id": filename,
        "path": str(path),
        "download_url": f"/api/download/{filename}",
    }


def render_screening_letter(screening_id: str, text: str) -> dict:
    """Render an approved queue item's letter, reusing an identical render.

    The reuse test is the filename itself: it carries a digest of the letter
    AND of the header rendered above it, so an existing file cannot be a render
    of anything else — with the one caveat that an empty file is no render at
    all, which is why size is checked. A zero-byte file at the digest name
    would otherwise be served forever, with nothing able to replace it.

    Digesting the header, not just the text, is what stops a profile edit from
    being invisible here: the operator changes their email, the CV picks it up
    on its next render, and without this the letter beside it would keep the
    superseded contact line with no path by which anything could notice.

    Editing either changes the name rather than overwriting the old file, and
    the predecessor is swept once the replacement is on disk.
    """
    if not text.strip():
        return dict(NO_FILE)
    try:
        # Imported here, not at module scope: this is the only function that
        # renders, and at module scope it would make all 17 tools fail to
        # import if the renderer's Jinja environment could not be built.
        from truthcv.engines.render.cover_letter import render_letter_pdf
        from truthcv.services.render_cv import _contact_line

        # Header composed exactly as the wizard's own renders compose it
        # (truthcv/services/render_cv.py), so the letter an employer receives from the
        # agent and the operator's own copy of it carry the same header.
        truth = load_truth()
        name = truth.profile.name or "Your Name"
        contact = _contact_line(truth.profile)
    except Exception:  # noqa: BLE001 — a bad truth store must not fail the queue read
        return dict(NO_FILE)

    try:
        filename = pdf_filename(screening_id, text, _header_digest(name, contact))
        path = pdf_path(screening_id, text, _header_digest(name, contact))
    except ValueError:
        return dict(NO_FILE)
    if path.exists() and path.stat().st_size > 0:
        return _asset(filename, path)

    try:
        rendered = render_letter_pdf(text, filename, name=name, contact=contact)
    except Exception:  # noqa: BLE001 — nothing here may fail a queue read
        return dict(NO_FILE)
    if rendered is None:
        return dict(NO_FILE)
    prune_pdfs(screening_id, keep=filename)
    return _asset(filename, rendered)
