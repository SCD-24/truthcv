"""Tests for render.verify.verify_pdf: does the produced PDF read back right?

Most cases drive the comparison deterministically by monkeypatching the
private extraction seam `render.verify._extract_pypdf`, so no PDF backend is
required. One integration test at the end renders and verifies a real PDF,
skipping cleanly when WeasyPrint is unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from render import verify as verify_mod
from render.verify import verify_pdf
from render.html import render_html
from render import pdf as pdf_mod
from tailor.model import Draft, DraftExperience

FAKE_PDF = Path("/fake/cv.pdf")


def _patch_extract(monkeypatch, text: str, pages: int = 1) -> None:
    monkeypatch.setattr(verify_mod, "_extract_pypdf", lambda path: (text, pages))


def test_clean_pdf_has_no_findings(monkeypatch):
    html = "<p>Senior Software Engineer at Acme Corp</p>"
    _patch_extract(monkeypatch, "Senior Software Engineer at Acme Corp")
    assert verify_pdf(FAKE_PDF, html) == []


def test_split_word_is_detected(monkeypatch):
    html = "<p>Vorantreiben</p>"
    _patch_extract(monkeypatch, "V orantreiben")
    findings = verify_pdf(FAKE_PDF, html)
    codes = {f["code"] for f in findings}
    assert "pdf-split-word" in codes
    msg = next(f["message"] for f in findings if f["code"] == "pdf-split-word")
    assert "v orantreiben" in msg
    assert "vorantreiben" in msg


def test_glued_words_is_detected(monkeypatch):
    html = "<p>Senior Software Engineer at Acme Corp</p>"
    _patch_extract(monkeypatch, "Senior Software EngineeratAcme Corp")
    findings = verify_pdf(FAKE_PDF, html)
    codes = {f["code"] for f in findings}
    assert "pdf-glued-words" in codes
    msg = next(f["message"] for f in findings if f["code"] == "pdf-glued-words")
    assert "engineeratacme" in msg
    assert "engineer at acme" in msg


def test_missing_text_is_detected(monkeypatch):
    html = "<p>Onboarded new hires and ran quarterly compliance audits</p>"
    _patch_extract(monkeypatch, "Something completely unrelated")
    findings = verify_pdf(FAKE_PDF, html)
    codes = {f["code"] for f in findings}
    assert "pdf-text-missing" in codes


def test_empty_extraction_yields_single_unreadable_finding(monkeypatch):
    html = "<p>Anything at all</p>"
    _patch_extract(monkeypatch, "")
    findings = verify_pdf(FAKE_PDF, html)
    assert len(findings) == 1
    assert findings[0]["code"] == "pdf-text-unreadable"


def test_page_count_over_target_warns(monkeypatch):
    html = "<p>hello world</p>"
    _patch_extract(monkeypatch, "hello world", pages=2)
    findings = verify_pdf(FAKE_PDF, html, max_pages=1)
    assert any(f["code"] == "pdf-page-count" for f in findings)


def test_page_count_within_or_unset_target_is_silent(monkeypatch):
    html = "<p>hello world</p>"
    _patch_extract(monkeypatch, "hello world", pages=2)
    findings = verify_pdf(FAKE_PDF, html, max_pages=None)
    assert not any(f["code"] == "pdf-page-count" for f in findings)


def test_missing_text_findings_are_capped(monkeypatch):
    missing = " ".join(f"missing{i}" for i in range(20))
    html = f"<p>filler text here {missing}</p>"
    _patch_extract(monkeypatch, "filler text here")
    findings = verify_pdf(FAKE_PDF, html)
    missing_findings = [f for f in findings if f["code"] == "pdf-text-missing"]
    assert len(missing_findings) == 6
    assert any("more" in f["message"] for f in missing_findings)


def test_verify_pdf_never_raises_on_a_bad_path():
    findings = verify_pdf(Path("/definitely/does/not/exist.pdf"), "<p>hi</p>")
    assert isinstance(findings, list)
    assert findings  # some warning is returned, not an exception


DRAFT = Draft(
    experiences=[
        DraftExperience(
            source_id="exp-1",
            role="Senior Software Engineer",
            company="Acme Corp",
            dates="2020 - 2023",
            bullets=["Built a payments API in Python"],
        )
    ],
    skills=["Python"],
    keywords=["Python"],
)


def test_real_produced_pdf_survives_verification(data_dir):
    html = render_html(DRAFT, name="Ada", contact="ada@example.com")
    try:
        out = pdf_mod.render_pdf(html)
    except pdf_mod.RenderUnavailable:
        pytest.skip("WeasyPrint not installed in this environment")
    findings = verify_pdf(out, html)
    codes = {f["code"] for f in findings}
    assert "pdf-text-unreadable" not in codes
    assert "pdf-text-missing" not in codes
