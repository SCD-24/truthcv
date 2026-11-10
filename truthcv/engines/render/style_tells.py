"""Style-tell checker: deterministic warnings for AI-sounding prose.

Pure and provider-agnostic: no LLM, no I/O. Returns a list of {code, message}
in the same shape as ``truthcv.engines.render.ats.lint``. Strong tells warn on one sighting;
weak tells warn only when several accumulate.

Patterns are drawn from humanizer's "Signs of AI writing"
(MIT, https://github.com/blader/humanizer).
"""

from __future__ import annotations

import re

from truthcv.engines.prompts.style import STRICT_TELL_WORDS

# Most distinct offending snippets quoted in one warning.
MAX_SNIPPETS = 5
# Weak tells warn only once this many accumulate across all weak families.
WEAK_TELL_THRESHOLD = 2

# A date-like token in a CV range: year, "Mon[.] YYYY", MM/YYYY, MM.YYYY,
# YYYY-MM, YYYY/MM, or an open-ended word.
_DATE_TOKEN = (
    r"(?:(?:[A-Za-z]{3,9}\.?\s+)?\d{4}(?![\d/-])"
    r"|\d{1,2}[/.]\d{4}"
    r"|\d{4}[-/]\d{2}"
    r"|(?:present|current|now|ongoing|today)\b)"
)
# The CV renderer joins date ranges with an en dash; those are deliberate.
_DATE_RANGE = re.compile(rf"{_DATE_TOKEN}\s*–\s*{_DATE_TOKEN}", re.I)
_DASH = re.compile(r"\w*\s*[—–]\s*\w*|\w*\s+--\s+\w*")
_CURLY_QUOTE = re.compile(r"[‘’“”]")
_TELL_WORD = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in STRICT_TELL_WORDS) + r")\b", re.I
)
_CHATBOT = re.compile(
    r"here is your|here['’]s your|i hope this helps|let me know if"
    r"|certainly!|of course!|as an ai|great question",
    re.I,
)
_WEAK = re.compile(
    r", (?:ensuring|driving|highlighting|showcasing|fostering|underscoring"
    r"|reflecting|contributing to|enabling)\b"
    r"|involved in|associated with"
    r"|contributed to|marking a"
    r"|played a key role|pivotal role|instrumental in|setting the stage",
    re.I,
)


def _snippets(pattern: re.Pattern[str], text: str) -> list[str]:
    """Distinct stripped matches in first-seen order, capped at MAX_SNIPPETS."""
    seen: dict[str, None] = {}
    for m in pattern.finditer(text):
        seen.setdefault(m.group(0).strip(), None)
    return list(seen)[:MAX_SNIPPETS]


def _warning(code: str, message: str, found: list[str]) -> dict[str, str]:
    quoted = ", ".join(f"'{s}'" for s in found)
    return {"code": code, "message": f"{message} Found: {quoted}."}


def _strong_warnings(text: str) -> list[dict[str, str]]:
    strong = (
        ("style-dash", "Em/en dashes and ' -- ' read as AI-written; use a comma or full stop.",
         _DASH, _DATE_RANGE.sub(" ", text)),
        ("style-curly-quote", "Curly quotes read as AI-written; use straight quotes.",
         _CURLY_QUOTE, text),
        ("style-tell-word", "Words that read as AI-written; use plainer wording.",
         _TELL_WORD, text),
        ("style-chatbot-residue", "Chatbot residue in the text; remove it.",
         _CHATBOT, text),
    )
    warnings = []
    for code, message, pattern, haystack in strong:
        found = _snippets(pattern, haystack)
        if found:
            warnings.append(_warning(code, message, found))
    return warnings


def check_style(text: str) -> list[dict[str, str]]:
    """Return style-tell warnings for ``text`` as {code, message} dicts."""
    warnings = _strong_warnings(text)
    weak_hits = [m.group(0).strip(", ") for m in _WEAK.finditer(text)]
    if len(weak_hits) >= WEAK_TELL_THRESHOLD:
        found = list(dict.fromkeys(weak_hits))[:MAX_SNIPPETS]
        warnings.append(_warning(
            "style-weak-tells",
            "Several filler phrasings that read as AI-written; state the fact directly.",
            found,
        ))
    return warnings
