"""Verify the PDF TruthCV actually produces, not the input HTML it came from.

render/ats.py::lint checks the HTML about to be rendered. This module checks
the artifact that comes OUT the other end: it extracts text back out of the
produced PDF and compares it against the expected visible text of that same
HTML, so a WeasyPrint/font/kerning defect that glues or splits words in the
PDF (or drops text entirely) surfaces as a warning even though the source
HTML was fine. Every finding here is a WARNING, in the same {code, message}
shape as render/ats.py::lint, meant to be merged straight into atsWarnings.
This module has no notion of failure: verify_pdf() never raises and never
blocks a render.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
import shutil
import subprocess
from pathlib import Path

from prompts.conventions import DEFAULT_CONVENTIONS, page_target_pages

from .ats import _visible_text

logger = logging.getLogger(__name__)

_MAX_PER_CODE = 5
_MAX_RUN = 4
_MIN_DISAGREEMENT_TOKENS = 3


def _tokenize(text: str) -> list[str]:
    """Normalise `text` into lowercase, entity-unescaped, whitespace tokens."""
    unescaped = html_lib.unescape(text)
    collapsed = re.sub(r"\s+", " ", unescaped).strip().lower()
    return [t for t in collapsed.split(" ") if re.search(r"[a-z0-9]", t)]


def _extract_pypdf(path: Path) -> tuple[str, int]:
    """Extract concatenated text and page count from a PDF via pypdf.

    Private seam so tests can monkeypatch extraction without a real PDF.
    """
    from pypdf import PdfReader  # imported lazily; heavy native deps

    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return text, len(reader.pages)


def _find_run_match(token: str, sequence: list[str]) -> str | None:
    """Find 2..N adjacent tokens in `sequence` that concatenate to `token`."""
    n = len(sequence)
    for start in range(n):
        joined = ""
        limit = min(_MAX_RUN, n - start)
        for run_len in range(1, limit + 1):
            joined += sequence[start + run_len - 1]
            if run_len >= 2 and joined == token:
                return " ".join(sequence[start : start + run_len])
    return None


def _cap(findings: list[dict[str, str]], code: str) -> list[dict[str, str]]:
    """Cap findings of one `code` at _MAX_PER_CODE, adding a '(+N more)' entry."""
    matching = [f for f in findings if f["code"] == code]
    if len(matching) <= _MAX_PER_CODE:
        return findings
    extra = len(matching) - _MAX_PER_CODE
    kept = matching[:_MAX_PER_CODE]
    kept.append({"code": code, "message": f"(+{extra} more)"})
    return [f for f in findings if f["code"] != code] + kept


def _split_word_findings(expected: list[str], actual_set: set[str], actual: list[str]):
    """Expected tokens missing from the PDF but recoverable by joining PDF tokens."""
    findings: list[dict[str, str]] = []
    explained: set[str] = set()
    for tok in dict.fromkeys(expected):
        if tok in actual_set:
            continue
        match = _find_run_match(tok, actual)
        if match:
            findings.append(
                {
                    "code": "pdf-split-word",
                    "message": f"PDF text reads '{match}' where it should read '{tok}'.",
                }
            )
            explained.add(tok)
    return findings, explained


def _glued_word_findings(actual: list[str], expected_set: set[str], expected: list[str]):
    """PDF tokens not in the expected text but formed by gluing expected words."""
    findings: list[dict[str, str]] = []
    for tok in dict.fromkeys(actual):
        if tok in expected_set:
            continue
        match = _find_run_match(tok, expected)
        if match:
            findings.append(
                {
                    "code": "pdf-glued-words",
                    "message": f"PDF text reads '{tok}' where it should read '{match}'.",
                }
            )
    return findings


def _missing_findings(expected: list[str], actual_set: set[str], explained: set[str]):
    """Expected tokens (len>=3) absent from the PDF and not explained by a split."""
    findings: list[dict[str, str]] = []
    for tok in dict.fromkeys(expected):
        if len(tok) < 3 or tok in actual_set or tok in explained:
            continue
        findings.append(
            {"code": "pdf-text-missing", "message": f"Expected text '{tok}' not found in the produced PDF."}
        )
    return findings


def _token_findings(expected: list[str], actual: list[str]) -> list[dict[str, str]]:
    """Compare expected vs. actual token streams; return capped findings."""
    expected_set, actual_set = set(expected), set(actual)
    split, explained = _split_word_findings(expected, actual_set, actual)
    glued = _glued_word_findings(actual, expected_set, expected)
    missing = _missing_findings(expected, actual_set, explained)
    findings = split + glued + missing
    for code in ("pdf-split-word", "pdf-glued-words", "pdf-text-missing"):
        findings = _cap(findings, code)
    return findings


def _page_count_findings(page_count: int, max_pages: int | None) -> list[dict[str, str]]:
    """Warn when the produced PDF exceeds the configured page target."""
    if max_pages is None or page_count <= max_pages:
        return []
    return [
        {"code": "pdf-page-count", "message": f"PDF is {page_count} pages; target is {max_pages}."}
    ]


def _pdftotext_probe(path: Path, pypdf_tokens: list[str]) -> list[dict[str, str]]:
    """Optional third-opinion cross-check via the pdftotext CLI, if it happens
    to be on PATH. Never raises; any failure is swallowed silently since
    pdftotext is not a project dependency."""
    if shutil.which("pdftotext") is None:
        return []
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            timeout=10,
            text=True,
            check=True,
        )
    except Exception:  # noqa: BLE001
        return []
    diff = set(_tokenize(result.stdout)).symmetric_difference(pypdf_tokens)
    if len(diff) < _MIN_DISAGREEMENT_TOKENS:
        return []
    sample = ", ".join(sorted(diff)[:2])
    return [
        {
            "code": "pdf-extractor-disagreement",
            "message": f"pdftotext and pypdf disagree on extracted text (e.g. '{sample}').",
        }
    ]


def _verify_pdf_unsafe(pdf_path: Path, html: str, max_pages: int | None) -> list[dict[str, str]]:
    """Do the extraction/comparison work; may raise on a bad path or PDF."""
    expected = _tokenize(_visible_text(html))
    text, page_count = _extract_pypdf(pdf_path)
    actual = _tokenize(text)
    if not actual:
        return [{"code": "pdf-text-unreadable", "message": "No extractable text found in the produced PDF."}]
    findings = _token_findings(expected, actual)
    findings += _page_count_findings(page_count, max_pages)
    findings += _pdftotext_probe(pdf_path, actual)
    return findings


def verify_pdf(pdf_path: Path, html: str, max_pages: int | None = None) -> list[dict[str, str]]:
    """Verify a produced PDF against the HTML it was rendered from.

    Extracts the PDF's text and compares it to `html`'s expected visible
    text, returning {code, message} warnings for split/glued/missing text
    and (when `max_pages` is given) an over-length document. Never raises:
    any extraction failure degrades to a single 'pdf-unverified' warning
    rather than breaking a render that otherwise succeeded.
    """
    try:
        return _verify_pdf_unsafe(pdf_path, html, max_pages)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF verification failed for %s: %s", pdf_path, exc)
        return [{"code": "pdf-unverified", "message": f"Could not verify the produced PDF: {exc}"}]


def default_max_pages() -> int | None:
    """Page-count ceiling implied by the default CV conventions' page_target."""
    return page_target_pages(DEFAULT_CONVENTIONS)
