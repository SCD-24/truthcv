"""Assemble cover-letter prose into ATS-plain HTML, and from it a PDF (reuses the render Jinja env)."""

from __future__ import annotations

import os
from pathlib import Path

from .html import _env
from .pdf import render_pdf


def render_letter_html(text: str, name: str = "Your Name", contact: str = "") -> str:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return _env.get_template("cover_letter.html.j2").render(
        name=name, contact=contact, paragraphs=paragraphs
    )


def render_letter_pdf(
    text: str, filename: str, name: str = "Your Name", contact: str = ""
) -> Path | None:
    """Render letter prose to a PDF on the data volume, or None if it could not be.

    Written to a temporary name and moved into place, because the renderer
    writes straight through to its destination: a failure part-way leaves a
    truncated file behind, and a caller that treats "the file exists" as "the
    render succeeded" would hand that stump to an employer. After this, the
    destination either does not exist or is a complete render.

    Best-effort by design: the caller is the agent tool surface, where a
    missing rendering backend must degrade to "no file to upload" rather than
    fail the application. Nothing downstream may treat a None as an error —
    it means the letter exists only as text.
    """
    html = render_letter_html(text, name=name, contact=contact)
    try:
        staged = render_pdf(html, f"{filename}.part")
    except Exception:  # noqa: BLE001 — see docstring: no render must fail an application
        return None
    final = staged.with_name(filename)
    try:
        os.replace(staged, final)
    except OSError:
        staged.unlink(missing_ok=True)
        return None
    return final
