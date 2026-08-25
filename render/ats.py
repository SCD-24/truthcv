"""ATS linter: deterministic checks on the rendered HTML.

Warns (does not block) on layout/structure that applicant-tracking systems parse
poorly, and on posting keywords absent from the CV. Pure and provider-agnostic.
Returns a list of {code, message} — the frontend renders these as atsWarnings.

Keyword matching here is now token/phrase-aware and strict-by-design
(contiguous-phrase matching) because it models what an ATS scanner actually
does: it only credits a keyword whose full phrase appears as an adjacent run. A
separate, looser check exists elsewhere (`tailor/infer.py`) for truth-coverage
purposes, which is intentionally more permissive.
"""

from __future__ import annotations

import logging
import re

from truth.store import data_dir
from vocabulary.match import ABSENT, ALIAS_ONLY, EXACT, INTERLEAVED, match_keyword

# Headings no ATS reviewer should warn about. The built-in set covers the
# common sections across academic, medical, legal and trade CVs too — not just
# tech — and an operator can extend it via data/vocabulary/ats_headings.txt
# (one heading per line, case-insensitive). Missing/unreadable file means
# built-ins only.
_BUILTIN_STANDARD_HEADINGS = {
    "summary",
    "profile",
    "experience",
    "work experience",
    "professional experience",
    "employment history",
    "skills",
    "education",
    "publications",
    "licences",
    "licenses",
    "certifications",
    "languages",
    "portfolio",
    "projects",
    "awards",
}

_VOCAB_DIR_NAME = "vocabulary"


def _standard_headings() -> frozenset[str]:
    """Built-in standard headings merged with any operator-supplied extras."""
    words = set(_BUILTIN_STANDARD_HEADINGS)
    path = data_dir() / _VOCAB_DIR_NAME / "ats_headings.txt"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return frozenset(words)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not read %s (%s); using built-in ATS headings only", path, exc
        )
        return frozenset(words)
    for line in lines:
        heading = line.strip().lower()
        if heading and not heading.startswith("#"):
            words.add(heading)
    return frozenset(words)


def _headings(html: str) -> list[str]:
    return [h.strip().lower() for h in re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.I | re.S)]


# <style>/<script> bodies and comments sit between tags, so stripping tags
# alone leaves their contents behind and they read as document text.
#
# One left-to-right pass, not two: whichever construct opens first must win.
# Stripping elements before comments lets a <style> inside a comment pair with
# the next real </style> and swallow the document in between; stripping
# comments first has the mirror flaw for a "<!--" inside CSS. Alternation with
# re.sub takes the leftmost match, which is what a real parser does.
_NON_TEXT = re.compile(
    r"<!--.*?-->"  # comment
    r"|<(style|script)\b[^>]*>.*?</\1\s*>"  # style/script with its closing tag
    r"|<(?:style|script)\b[^>]*>.*",  # unclosed: everything after it is not text
    re.I | re.S,
)


def _visible_text(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", _NON_TEXT.sub(" ", html)).lower()


def _keyword_warning(kw: str, verdict: str) -> dict[str, str] | None:
    """Map a `match_keyword` verdict to an ATS warning, or None for a clean match."""
    name = kw.strip()
    if verdict == EXACT:
        return None
    if verdict == INTERLEAVED:
        return {
            "code": "interleaved-keyword",
            "message": (
                f"Posting keyword '{name}' appears only with words in between "
                f"(e.g. write 'unit tests and integration tests', not "
                f"'unit and integration tests'); repeat the full phrase so an "
                f"ATS scanning for a contiguous match can see it."
            ),
        }
    if verdict == ALIAS_ONLY:
        return {
            "code": "missing-keyword-form",
            "message": (
                f"Only an alternate form of posting keyword '{name}' appears in "
                f"the CV; ATS keyword taxonomies treat an acronym and its "
                f"expansion as unrelated entries, so consider adding '{name}' "
                f"itself as well."
            ),
        }
    # verdict == ABSENT (or any other): keyword's phrase is nowhere in the CV.
    assert verdict == ABSENT
    return {
        "code": "missing-keyword",
        "message": f"Posting keyword '{name}' does not appear in the CV.",
    }


def lint(
    html: str, keywords: list[str] | None = None, aliases: dict[str, list[str]] | None = None
) -> list[dict[str, str]]:
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
    nonstandard = headings - _standard_headings()
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
        if not kw.strip():
            continue
        verdict = match_keyword(kw, text, (aliases or {}).get(kw, []))
        warning = _keyword_warning(kw, verdict)
        if warning is not None:
            warnings.append(warning)

    return warnings
