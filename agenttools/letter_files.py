"""The letter as a *file*, for the tool that hands the agent something to upload.

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

Every function is best-effort. When no rendering backend is installed — or any
part of rendering fails — the returned path is None, which means "this letter
exists only as text", never an error. A read of the approved queue must not be
able to fail because a PDF could not be produced.
"""

from __future__ import annotations

from pathlib import Path

from coverletter.store import pdf_filename, pdf_path, prune_pdfs
from truth.store import load as load_truth

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
        from render.cover_letter import render_letter_pdf
        from services.render_cv import _contact_line

        # Header composed exactly as the wizard's own renders compose it
        # (services/render_cv.py), so the letter an employer receives from the
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
