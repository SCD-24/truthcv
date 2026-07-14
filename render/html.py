"""Assemble the structured draft into ATS-safe HTML via Jinja2.

Each experience renders as its own block — a heading (role, company — dates) with
that job's bullets beneath it — so a date or bullet stays with the job it belongs
to. Education and skills render into their own sections. This module NEVER
introduces new facts; it only arranges the approved draft.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from tailor.model import Draft

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
)


def _heading(title_parts: list[str], dates: str) -> str:
    title = ", ".join(p for p in title_parts if p)
    return f"{title} — {dates}" if title and dates else (title or dates)


def _context(draft: Draft) -> dict[str, Any]:
    """Build the template context from the structured draft."""
    experience = [
        {"heading": _heading([e.role, e.company], e.dates), "bullets": e.bullets}
        for e in draft.experiences
        if e.role or e.company or e.bullets
    ]
    education = [
        _heading([ed.degree, ed.school], ed.dates)
        for ed in draft.education
        if ed.degree or ed.school
    ]
    return {"experience": experience, "skills": list(draft.skills), "education": education}


def render_html(
    draft: Draft,
    name: str = "Your Name",
    contact: str = "",
    summary: str = "",
    email: str = "",
    phone: str = "",
    location: str = "",
    links: list[dict[str, str]] | None = None,
) -> str:
    """Render the CV to ATS-safe HTML.

    The header takes either structured identity fields (email/phone/location/
    links) or a pre-composed ``contact`` string; the template prefers the
    structured fields when present. All are optional so existing callers and the
    guardrail-blocked path are unaffected.
    """
    ctx = _context(draft)
    ctx.update(
        name=name,
        contact=contact,
        summary=summary,
        email=email,
        phone=phone,
        location=location,
        links=links or [],
    )
    template = _env.get_template("cv.html.j2")
    return template.render(**ctx)
