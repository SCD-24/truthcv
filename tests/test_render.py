"""Renderer tests: HTML assembly, ATS linter, and best-effort PDF/DOCX smoke.

render_html now takes a structured `Draft` (experiences/education/skills), not a
flat list of entry dicts. Each experience renders as its own block.
"""

from __future__ import annotations

import pytest

from render.html import render_html
from render.cover_letter import render_letter_html
from render.ats import lint
from render import pdf as pdf_mod
from render import docx as docx_mod
from tailor.model import Draft, DraftExperience
import vocabulary.synonyms as vocab_synonyms


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


def test_cover_letter_header_shows_name_once():
    """The candidate's name renders once in the letterhead. The body carries no
    name (the prompt forbids it), so the name must not appear a second time."""
    body = "Dear Hiring Manager,\n\nI build payments systems in Python.\n\nBest,"
    html = render_letter_html(body, name="Ada Lovelace", contact="ada@example.com")
    visible = html.split("<body>", 1)[1]
    # Name appears exactly once in the rendered document body: the letterhead.
    assert visible.count("Ada Lovelace") == 1
    assert "ada@example.com" in visible
    assert "<h1>Ada Lovelace</h1>" in html


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
        "<h2>Interests</h2>"
        "</body></html>"
    )
    warnings = lint(bad, keywords=["Kubernetes"])
    codes = {w["code"] for w in warnings}
    assert "table" in codes
    assert "multi-column" in codes
    assert "missing-keyword" in codes
    assert "nonstandard-heading" in codes
    assert "missing-contact" in codes


def test_ats_accepts_common_non_tech_headings(data_dir):
    """Publications and similar sections no longer warn as non-standard."""
    html = (
        "<html><body>"
        "<h2>Summary</h2><p>x</p><h2>Experience</h2><p>y</p>"
        "<h2>Publications</h2><p>z</p><h2>Licences</h2><p>w</p>"
        "<h2>Certifications</h2><p>a</p><h2>Languages</h2><p>b</p>"
        "<p>ada@example.com</p>"
        "</body></html>"
    )
    warnings = lint(html)
    codes = {w["code"] for w in warnings}
    assert "nonstandard-heading" not in codes


def test_ats_honours_operator_supplied_headings(data_dir):
    """A heading listed on the data volume is treated as standard."""
    html = "<html><body><h2>Patents</h2><p>x</p></body></html>"
    assert any(w["code"] == "nonstandard-heading" for w in lint(html))
    vocab_dir = data_dir / "vocabulary"
    vocab_dir.mkdir()
    (vocab_dir / "ats_headings.txt").write_text("Patents\n", encoding="utf-8")
    assert not any(w["code"] == "nonstandard-heading" for w in lint(html))


def test_pdf_smoke_or_skip(data_dir):
    html = render_html(DRAFT, name="Ada", contact="ada@example.com")
    try:
        out = pdf_mod.render_pdf(html)
    except pdf_mod.RenderUnavailable:
        pytest.skip("WeasyPrint not installed in this environment")
    assert out.exists() and out.stat().st_size > 0

    from pypdf import PdfReader

    reader = PdfReader(str(out))
    assert len(reader.pages) == 1
    text = " ".join((page.extract_text() or "") for page in reader.pages)
    normalized = " ".join(text.split()).lower()
    assert "ada" in normalized or "ada@example.com" in normalized
    assert "senior software engineer" in normalized
    assert "acme corp" in normalized
    assert "python" in normalized


def test_docx_smoke_or_skip(data_dir):
    html = render_html(DRAFT, name="Ada", contact="ada@example.com")
    try:
        out = docx_mod.render_docx(html)
    except docx_mod.RenderUnavailable:
        pytest.skip("pandoc not installed in this environment")
    assert out.exists() and out.stat().st_size > 0


def test_ats_flags_interleaved_keyword():
    """A keyword phrase whose words are spliced apart ('unit and integration
    tests' for 'unit tests') is not a contiguous ATS match: it must be flagged
    as interleaved, not reported as missing."""
    html = (
        "<html><body>"
        "<p>Wrote unit and integration tests for the platform. "
        "Contact: ada@example.com</p>"
        "</body></html>"
    )
    warnings = lint(html, keywords=["unit tests"])
    codes = {w["code"] for w in warnings}
    assert "interleaved-keyword" in codes
    assert "missing-keyword" not in codes


def test_ats_flags_missing_keyword_form_from_aliases_arg():
    """When only an alias form (the expansion) of the keyword is present, and the
    equivalence is supplied via the `aliases` argument, the linter reports
    missing-keyword-form rather than missing-keyword."""
    html = (
        "<html><body>"
        "<p>Ran Continuous Integration and Continuous Delivery pipelines. "
        "Contact: ada@example.com</p>"
        "</body></html>"
    )
    warnings = lint(
        html,
        keywords=["CI/CD"],
        aliases={"CI/CD": ["Continuous Integration and Continuous Delivery"]},
    )
    codes = {w["code"] for w in warnings}
    assert "missing-keyword-form" in codes
    assert "missing-keyword" not in codes


def test_ats_flags_missing_keyword_form_from_synonyms_file(data_dir):
    """The same missing-keyword-form verdict is driven purely by an operator
    synonyms.txt file (no `aliases` argument), loaded via vocabulary.synonyms."""
    vocab_dir = data_dir / "vocabulary"
    vocab_dir.mkdir()
    (vocab_dir / "synonyms.txt").write_text(
        "CI/CD = Continuous Integration and Continuous Delivery\n", encoding="utf-8"
    )
    # Reset the per-process synonyms cache so the freshly written file is read.
    vocab_synonyms._synonyms_cache = None
    html = (
        "<html><body>"
        "<p>Ran Continuous Integration and Continuous Delivery pipelines. "
        "Contact: ada@example.com</p>"
        "</body></html>"
    )
    warnings = lint(html, keywords=["CI/CD"])
    codes = {w["code"] for w in warnings}
    assert "missing-keyword-form" in codes


def test_ats_go_is_not_a_substring_of_django():
    """Regression: token-aware matching must not credit 'Go' just because the
    letters appear inside 'Django'. 'Go' is genuinely absent here."""
    html = (
        "<html><body>"
        "<p>Built services in Django. Contact: ada@example.com</p>"
        "</body></html>"
    )
    warnings = lint(html, keywords=["Go"])
    codes = {w["code"] for w in warnings}
    assert "missing-keyword" in codes
