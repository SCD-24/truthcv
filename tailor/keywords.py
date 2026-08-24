"""Extract targeting keywords from a job posting."""

from __future__ import annotations

import logging
from typing import Any

from providers.base import LLMProvider
from truth.store import data_dir

import prompts

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"keywords": {"type": "array", "items": {"type": "string"}}},
    "required": ["keywords"],
}

# Work-arrangement / location markers — never screenable skills, so a keyword
# built around them ('Remote in <city>') pollutes the ATS review. Built-in
# English set; an operator can extend it via data/vocabulary/arrangement_words.txt.
_BUILTIN_ARRANGEMENT_WORDS = frozenset(
    {"remote", "hybrid", "onsite", "on-site", "relocation", "relocate", "based in"}
)
# Seniority prefixes that mark a bare job title ('Senior Data Engineer') rather
# than a skill. Matched only at the start of a token to stay conservative.
# The built-in ladder covers the common English titles; an operator extends it
# via data/vocabulary/seniority_prefixes.txt (one prefix per line, trailing
# space optional — it is normalised on).
_BUILTIN_SENIORITY_PREFIXES = (
    "senior ",
    "junior ",
    "lead ",
    "principal ",
    "staff ",
    "head of ",
    "chief ",
    "associate ",
    "director ",
    "mid-level ",
    "entry-level ",
)

_VOCAB_DIR_NAME = "vocabulary"


def _read_vocab_lines(filename: str) -> list[str]:
    """Lines from a vocabulary file on the data volume; [] if absent/unreadable.

    Missing or unreadable means built-ins only — the junk filter degrades to
    today's exact behaviour rather than failing extraction.
    """
    path = data_dir() / _VOCAB_DIR_NAME / filename
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not read %s (%s); using built-in values only", path, exc
        )
        return []
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def arrangement_words() -> frozenset[str]:
    """Built-in arrangement words merged with any operator-supplied extras."""
    return frozenset(_BUILTIN_ARRANGEMENT_WORDS | set(_read_vocab_lines("arrangement_words.txt")))


def seniority_prefixes() -> tuple[str, ...]:
    """Built-in seniority prefixes plus operator-supplied ones, each 'x '-shaped."""
    extra = tuple(
        p if p.endswith(" ") else f"{p} "
        for p in _read_vocab_lines("seniority_prefixes.txt")
    )
    seen: set[str] = set()
    out: list[str] = []
    for prefix in (*_BUILTIN_SENIORITY_PREFIXES, *extra):
        low = prefix.lower()
        if low not in seen:
            seen.add(low)
            out.append(low)
    return tuple(out)


def _is_junk_token(keyword: str) -> bool:
    """True when a keyword is a location/arrangement/title, not a real skill.

    Deterministic safety net behind the tightened extraction prompt: even if the
    model slips a non-skill through, it never reaches the ATS keyword review.
    Conservative by design — only clear location/arrangement/title shapes match,
    so genuine skills are never dropped.
    """
    low = keyword.lower()
    if any(word in low for word in arrangement_words()):
        return True
    return low.startswith(seniority_prefixes())


def extract_keywords(posting: str, provider: LLMProvider) -> list[str]:
    """Return an ordered, de-duplicated list of screenable posting keywords."""
    if not posting or not posting.strip():
        return []
    result = provider.extract_json(
        prompts.keywords_system(), [{"role": "user", "content": posting}], _SCHEMA
    )
    raw = result.get("keywords", []) if isinstance(result, dict) else []
    seen: set[str] = set()
    out: list[str] = []
    for k in raw:
        kw = str(k).strip()
        low = kw.lower()
        if kw and low not in seen and not _is_junk_token(kw):
            seen.add(low)
            out.append(kw)
    return out
