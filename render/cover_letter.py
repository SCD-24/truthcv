"""Assemble cover-letter prose into ATS-plain HTML, and from it a PDF (reuses the render Jinja env)."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from storage import data_dir

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

    Rendered under a name unique to this write and moved into place, for the
    two reasons ``storage/atomic.py`` records for the JSON stores: the renderer
    writes straight through to its destination, so a failure part-way leaves a
    truncated file a caller would mistake for a finished one; and a temp name
    shared between writers is worse than no temp name at all, because two
    concurrent renders truncate each other's buffer and the survivor is a
    splice of both. After this, the destination is either absent or a complete
    render, whoever else is rendering.

    Best-effort by design: the caller is the agent tool surface, where a
    missing rendering backend must degrade to "no file to upload" rather than
    fail the application. Nothing downstream may treat a None as an error —
    it means the letter exists only as text.
    """
    html = render_letter_html(text, name=name, contact=contact)
    stage_name = f"{filename}.{uuid4().hex}.part"
    try:
        staged = render_pdf(html, stage_name)
    except Exception:  # noqa: BLE001 — see docstring: no render must fail an application
        # The renderer may have created the stage before failing. Nothing else
        # can be holding this name, so removing it cannot cost another writer.
        (data_dir() / stage_name).unlink(missing_ok=True)
        return None
    final = staged.with_name(filename)
    try:
        os.replace(staged, final)
    except OSError:
        staged.unlink(missing_ok=True)
        return None
    return final
