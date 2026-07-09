"""Assemble cover-letter prose into ATS-plain HTML (reuses the render Jinja env)."""

from __future__ import annotations

from .html import _env


def render_letter_html(text: str, name: str = "Your Name", contact: str = "") -> str:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return _env.get_template("cover_letter.html.j2").render(
        name=name, contact=contact, paragraphs=paragraphs
    )
