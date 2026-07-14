"""Renderer tests: HTML assembly, ATS linter, and best-effort PDF/DOCX smoke.

render_html now takes a structured `Draft` (experiences/education/skills), not a
flat list of entry dicts. Each experience renders as its own block.
"""

from __future__ import annotations

import pytest

from render.html import render_html
from render.ats import lint
from render import pdf as pdf_mod
from render import docx as docx_mod
from tailor.model import Draft, DraftExperience


DRAFT = Draft(
    experiences=[
        DraftExperience(
            source_id="exp-1",
            role="Senior Software Engineer",
            company="Acme Corp",
            dates="2020 – 2023",
            bullets=["Built a payments API in Python"],
        )
    ],
    skills=["Python"],
    keywords=["Python"],
)


def test_render_html_single_column_no_table():
    html = render_html(DRAFT, name="Ada Lovelace", contact="ada@example.com", summary="Engineer.")
    assert "<table" not in html.lower()
    assert "Senior Software Engineer" in html
    assert "Acme Corp" in html
    assert "Built a payments API in Python" in html
    assert "Python" in html
    assert "ada@example.com" in html


def test_render_html_structured_profile_header():
    html = render_html(
        DRAFT,
        name="Jane Doe",
        email="jane@example.com",
        phone="+1 555 0100",
        location="Berlin",
        links=[{"label": "LinkedIn", "url": "https://li/jane"}],
        summary="Backend engineer who ships",
    )
    assert "Jane Doe" in html
    assert "jane@example.com" in html
    assert "+1 555 0100" in html
    assert "Berlin" in html
    assert "https://li/jane" in html
    assert "Backend engineer who ships" in html
    assert "<table" not in html.lower()  # still ATS-safe


def test_ats_passes_good_html():
    html = render_html(DRAFT, name="Ada", contact="ada@example.com")
    warnings = lint(html, keywords=["Python"])
    codes = {w["code"] for w in warnings}
    assert "table" not in codes
    assert "multi-column" not in codes
    assert "missing-keyword" not in codes


def test_ats_flags_table_and_multicolumn_and_missing_keyword():
    bad = (
        "<html><body>"
        "<div style='column-count:2'><table><tr><td>x</td></tr></table></div>"
        "<h2>Profile</h2>"
        "</body></html>"
    )
    warnings = lint(bad, keywords=["Kubernetes"])
    codes = {w["code"] for w in warnings}
    assert "table" in codes
    assert "multi-column" in codes
    assert "missing-keyword" in codes
    assert "nonstandard-heading" in codes
    assert "missing-contact" in codes


def test_pdf_smoke_or_skip(data_dir):
    html = render_html(DRAFT, name="Ada", contact="ada@example.com")
    try:
        out = pdf_mod.render_pdf(html)
    except pdf_mod.RenderUnavailable:
        pytest.skip("WeasyPrint not installed in this environment")
    assert out.exists() and out.stat().st_size > 0


def test_docx_smoke_or_skip(data_dir):
    html = render_html(DRAFT, name="Ada", contact="ada@example.com")
    try:
        out = docx_mod.render_docx(html)
    except docx_mod.RenderUnavailable:
        pytest.skip("pandoc not installed in this environment")
    assert out.exists() and out.stat().st_size > 0
