"""Cover-letter workflow: resolve the posting, build a guardrail-truthful
letter, then produce best-effort PDF/DOCX files.

Framework-free — nothing here imports FastAPI. The HTTP adapter in
``api/routes.py`` marshals a ``CoverLetterRequest`` into the explicit arguments
this module takes and turns the returned :class:`CoverLetterOutcome` back into
the wire ``CoverLetterResult``. It also owns the two responses this module
deliberately does NOT raise for itself: a missing posting (:class:`DraftMissing`
-> HTTP 400) and a pure preview whose render backend was unavailable (HTTP 500).

Mirrors ``services/render_cv.py``: the guardrail runs inside ``build_letter``
before any file is produced, and a blocked letter comes back ``blocked=True``
with the unverifiable tokens and the flagged claims — nothing is rendered.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import applications as app_store
import coverletter
from coverletter import LETTER_SCOPE_ID, load_letter_draft
from render import render_docx, render_pdf
from render.cover_letter import render_letter_html
from render.pdf import RenderUnavailable
from services.render_cv import (
    DraftMissing,
    RenderedClaim,
    _claim_id,
    _contact_line,
)
from storage import data_dir
from truth import load
from truth.answers import load as load_answers


@dataclass
class CoverLetterOutcome:
    """Everything the HTTP adapter needs to build a ``CoverLetterResult``.

    The service deliberately does NOT decide the "no application and no output"
    hard-error case — the adapter owns that (it maps to HTTP 500, not the 503 a
    ``services.errors`` exception would produce).
    """

    blocked: bool = False
    unverifiable: list[str] = field(default_factory=list)
    blocked_claims: list[RenderedClaim] = field(default_factory=list)
    pdf_url: str | None = None
    docx_url: str | None = None
    text: str | None = None
    render_unavailable: bool = False


def _letter_approvals(
    approved_ids: set[str],
    denied_ids: set[str],
    posting: str,
) -> tuple[set[str], set[str], list[dict] | None]:
    """Resolve blocked-claim ids to claim texts against the CACHED letter draft.

    Mirrors /api/render: ids are recomputed from the persisted paragraphs (same
    LETTER_SCOPE_ID + _claim_id hash), so a decision the UI made on a blocked
    attempt re-validates the exact letter the user saw. Returns
    (approved_texts, denied_texts, paragraphs); paragraphs is None on a first
    generate so build_letter produces and caches a fresh letter. The cached
    draft is looked up by ``posting`` so a draft generated for a different
    posting is never reused for this approve/deny re-check.
    """
    if not (approved_ids or denied_ids):
        return set(), set(), None

    paragraphs = load_letter_draft(posting)
    if paragraphs is None:
        return set(), set(), None

    approved: set[str] = set()
    denied: set[str] = set()
    for para in paragraphs:
        for claim in para.get("claims", []):
            cid = _claim_id(LETTER_SCOPE_ID, claim)
            if cid in approved_ids:
                approved.add(claim)
            if cid in denied_ids:
                denied.add(claim)
    return approved, denied, paragraphs


def generate_cover_letter(
    *,
    application_id: str | None,
    posting: str | None,
    tone: str,
    length: str,
    provider,
    approved_ids: set[str],
    denied_ids: set[str],
    preset_id: str | None = None,
) -> CoverLetterOutcome:
    """Run the full cover-letter workflow and return a plain outcome.

    Raises ``DraftMissing`` when no posting text is available (so the adapter can
    return its own 400), and lets any failure from ``build_letter`` propagate
    uncaught (so the adapter converts it to the exact 502 response).

    ``preset_id`` (optional) selects a writing style preset; when omitted,
    tone-based selection applies.
    """
    # The caller supplies the posting this letter is about; data/posting.txt
    # (the last posting written by /api/tailor) is only the fallback for
    # callers — like the wizard's Letter tab — that do not send one. This
    # workflow never writes posting.txt itself.
    text = (posting or "").strip()
    if not text:
        posting_file = data_dir() / "posting.txt"
        if posting_file.exists():
            text = posting_file.read_text(encoding="utf-8").strip()
    if not text:
        raise DraftMissing()
    posting = text

    approved_texts, denied_texts, paragraphs = _letter_approvals(
        approved_ids, denied_ids, posting
    )

    # The profile answers (Agents page) are handed to the writer as allowed
    # claim sources for this generation only, never written to truth.
    answers = load_answers()
    truth = load()
    # Call through the module (not a bound name) so tests that monkeypatch
    # `coverletter.build_letter` — patching the module attribute rather than
    # this module's own local binding — still take effect.
    letter = coverletter.build_letter(
        posting,
        tone,
        length,
        truth,
        provider,
        approved_texts=approved_texts,
        denied_texts=denied_texts,
        paragraphs=paragraphs,
        answers=answers,
        # The operator's name from the Agents page signs the letter. Their
        # truth-store profile name is the fallback, so a letter is never left
        # unsigned just because that field has not been filled in.
        sign_off_name=answers.name or truth.profile.name,
        preset_id=preset_id,
    )

    if letter["blocked"]:
        blocked_claims = [
            RenderedClaim(
                claim_id=_claim_id(c.scope_id, c.text),
                experience_id=c.scope_id,
                text=c.text,
                tokens=c.tokens,
            )
            for c in letter["blocked_claims"]
        ]
        return CoverLetterOutcome(
            blocked=True,
            unverifiable=letter["unverifiable"],
            blocked_claims=blocked_claims,
        )

    profile = truth.profile
    html = render_letter_html(
        letter["text"],
        name=profile.name or "Your Name",
        contact=_contact_line(profile),
    )

    # Attach to an application when asked (per-application files + persisted
    # document); otherwise render to the shared scratch filenames. The id was
    # already validated at entry, so a truthy app_id here is known to exist.
    app_id = application_id
    if app_id:
        pdf_name, docx_name = app_store.cover_letter_filenames(app_id)
    else:
        pdf_name, docx_name = "cover_letter.pdf", "cover_letter.docx"

    # Record the cover letter FIRST when attaching, so its link always
    # persists; then render best-effort.
    if app_id:
        app_store.save_cover_letter_document(app_id, letter["text"])

    pdf_url = docx_url = None
    try:
        pdf_url = f"/api/download/{render_pdf(html, pdf_name).name}"
    except RenderUnavailable:
        pass
    try:
        docx_url = f"/api/download/{render_docx(html, docx_name).name}"
    except RenderUnavailable:
        pass

    return CoverLetterOutcome(
        blocked=False,
        pdf_url=pdf_url,
        docx_url=docx_url,
        text=letter["text"],
        # Attached save that produced no file: the letter source is recorded but
        # its links are null, so tell the UI rather than silently show none.
        render_unavailable=bool(app_id) and pdf_url is None and docx_url is None,
    )
