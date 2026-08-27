"""The letter as a *file*, for tools that hand the agent something to upload.

Most ATS forms take the cover letter as an upload rather than a textarea, and
the browser container can only upload a path that exists on the shared data
volume. So the two tools that already carry guardrail-vouched letter text —
`generate_cover_letter` and `get_approved_applications` — render that exact
text to a PDF here and return its path alongside it.

Rendering lives behind those two tools ON PURPOSE, and there is deliberately no
"render this text" tool: a tool that turned arbitrary model-supplied prose into
an uploadable file would be a complete bypass of the cover-letter guardrail.
The only files that exist are renders of text the guardrail passed or the
operator wrote.

Every function here is best-effort. When no rendering backend is installed the
returned path is None, which means "this letter exists only as text" — never an
error.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from coverletter.store import pdf_filename, pdf_path
from render.cover_letter import render_letter_pdf
from services.render_cv import _contact_line as contact_line
from truth.answers import load as load_answers
from truth.store import load as load_truth

NO_FILE = {"asset_id": None, "path": None, "download_url": None}


def _header() -> tuple[str, str]:
    """The name and contact line the letter's header carries.

    Same rule the wizard and `generate_cover_letter`'s sign-off use: the
    operator's Agents-page name, falling back to the truth-store profile. The
    contact line is the real, un-aliased address — the per-company `tcv_`
    tracking address is for form fields, not for the document itself, and it is
    composed by the same helper the wizard's own renders use, so an agent-sent
    letter and an operator-sent one carry an identical header.
    """
    truth = load_truth()
    answers = load_answers()
    return (answers.name or truth.profile.name or "Your Name"), contact_line(truth.profile)


def _asset(filename: str, path: Path | None) -> dict:
    if path is None:
        return dict(NO_FILE)
    return {
        "asset_id": filename,
        "path": str(path),
        "download_url": f"/api/download/{filename}",
    }


def render_generated_letter(text: str) -> dict:
    """Render a just-generated letter, named by a digest of its own text.

    Content-addressed rather than named after the application, because
    `generate_cover_letter` is stateless by design: it is handed no id it could
    name a file after, and N concurrent applications must not clobber one
    another's file. Two calls that produce the same letter produce the same
    file, which is idempotent rather than a collision.
    """
    if not text.strip():
        return dict(NO_FILE)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    filename = f"cover_letter_draft_{digest}.pdf"
    name, contact = _header()
    return _asset(filename, render_letter_pdf(text, filename, name=name, contact=contact))


def _is_stale(path: Path, updated_at: str) -> bool:
    """True when the rendered file predates the draft it was rendered from."""
    if not updated_at:
        return False
    try:
        stamp = datetime.fromisoformat(updated_at).timestamp()
    except ValueError:
        # An unparseable stamp must not pin a stale PDF in place forever.
        return True
    return path.stat().st_mtime < stamp


def render_screening_letter(screening_id: str, text: str, updated_at: str) -> dict:
    """Render an approved queue item's stored letter, reusing the last render.

    Takes the letter's text and timestamp rather than the draft object because
    the approved-queue read has already loaded it — see
    ``services.applications.gather_approvable_screenings``. Re-rendered only
    when the file is missing or older than the draft, so a queue read does not
    pay for WeasyPrint once per approved item per run.
    """
    if not text.strip():
        return dict(NO_FILE)
    try:
        filename, path = pdf_filename(screening_id), pdf_path(screening_id)
    except ValueError:
        return dict(NO_FILE)
    if path.exists() and not _is_stale(path, updated_at):
        return _asset(filename, path)
    name, contact = _header()
    return _asset(
        filename, render_letter_pdf(text, filename, name=name, contact=contact)
    )
