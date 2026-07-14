"""ATS linter: deterministic checks on the rendered HTML.

Warns (does not block) on layout/structure that applicant-tracking systems parse
poorly, and on posting keywords absent from the CV. Pure and provider-agnostic.
Returns a list of {code, message} — the frontend renders these as atsWarnings.
"""

from __future__ import annotations

import re

_STANDARD_HEADINGS = {"summary", "experience", "skills", "education"}


def _headings(html: str) -> list[str]:
    return [h.strip().lower() for h in re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.I | re.S)]


def _visible_text(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html).lower()


def lint(html: str, keywords: list[str] | None = None) -> list[dict[str, str]]:
    """Return ATS warnings for `html` given the target `keywords`."""
    warnings: list[dict[str, str]] = []
    low = html.lower()

    if "<table" in low:
        warnings.append(
            {"code": "table", "message": "CV contains a table; many ATS parsers mangle tabular layouts."}
        )
    # crude multi-column detection
    if re.search(r"column-count\s*:\s*[2-9]", low) or re.search(r"float\s*:\s*(left|right)", low):
        warnings.append(
            {"code": "multi-column", "message": "Multi-column layout detected; use a single column for ATS."}
        )
    if "<img" in low:
        warnings.append(
            {"code": "image-text", "message": "Image detected; text inside images is invisible to ATS."}
        )

    headings = set(_headings(html))
    nonstandard = headings - _STANDARD_HEADINGS
    if nonstandard:
        warnings.append(
            {
                "code": "nonstandard-heading",
                "message": "Non-standard section heading(s): "
                + ", ".join(sorted(nonstandard))
                + ". Prefer Summary/Experience/Skills/Education.",
            }
        )

    text = _visible_text(html)
    if not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text) and not re.search(r"\+?\d[\d\s().-]{7,}", text):
        warnings.append(
            {"code": "missing-contact", "message": "No contact block (email or phone) detected."}
        )

    for kw in keywords or []:
        if kw.strip() and kw.strip().lower() not in text:
            warnings.append(
                {
                    "code": "missing-keyword",
                    "message": f"Posting keyword '{kw.strip()}' does not appear in the CV.",
                }
            )

    return warnings
