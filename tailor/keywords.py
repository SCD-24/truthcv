"""Extract targeting keywords from a job posting."""

from __future__ import annotations

import logging
from typing import Any

from providers.base import LLMProvider
from truth.store import data_dir

import prompts

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "keywords": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["term"],
            },
        }
    },
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


def _parse_keyword_item(item: Any) -> tuple[str, list[str]]:
    """Split one raw keyword item into (term, raw_aliases).

    Accepts both the new object shape ({"term", "aliases"}) and the legacy flat
    string shape, which carries no aliases.
    """
    if isinstance(item, dict):
        return str(item.get("term", "")).strip(), list(item.get("aliases", []) or [])
    return str(item).strip(), []


def _dedupe_aliases(raw_aliases: list[Any]) -> list[str]:
    """Strip, drop empties, and de-duplicate aliases case-insensitively (first-seen)."""
    seen: set[str] = set()
    out: list[str] = []
    for alias in raw_aliases:
        text = str(alias).strip()
        low = text.lower()
        if text and low not in seen:
            seen.add(low)
            out.append(text)
    return out


def extract_keywords_with_aliases(
    posting: str, provider: LLMProvider
) -> tuple[list[str], dict[str, list[str]]]:
    """Extract screenable keywords plus their model-supplied alternate phrasings.

    Terms are filtered exactly as :func:`extract_keywords` filters them (deduped
    by lowercase, empties and junk tokens dropped, order preserved). Aliases are
    alternate phrasings of an already-approved term (e.g. an acronym and its
    spelled-out expansion), deduped case-insensitively but NOT junk-filtered.

    WARNING: these aliases come from the LLM and must NEVER be fed to the
    guardrail as truth-equivalent — a model-supplied alias must never widen what
    counts as truth. Only the operator's own data/vocabulary/synonyms.txt file
    (loaded by vocabulary/synonyms.py, a separate, unrelated mechanism) is
    trusted for that.

    Args:
        posting: The raw job posting text.
        provider: The LLM provider used to extract structured keywords.

    Returns:
        A tuple of (ordered de-duplicated term list, alias map). The alias map is
        keyed by the exact stripped term strings and only holds terms that have
        at least one non-empty alias.
    """
    if not posting or not posting.strip():
        return [], {}
    result = provider.extract_json(
        prompts.keywords_system(), [{"role": "user", "content": posting}], _SCHEMA
    )
    raw = result.get("keywords", []) if isinstance(result, dict) else []
    seen: set[str] = set()
    terms: list[str] = []
    aliases: dict[str, list[str]] = {}
    for item in raw:
        term, raw_aliases = _parse_keyword_item(item)
        low = term.lower()
        if not term or low in seen or _is_junk_token(term):
            continue
        seen.add(low)
        terms.append(term)
        deduped = _dedupe_aliases(raw_aliases)
        if deduped:
            aliases[term] = deduped
    return terms, aliases


def extract_keywords(posting: str, provider: LLMProvider) -> list[str]:
    """Return an ordered, de-duplicated list of screenable posting keywords.

    Thin wrapper over :func:`extract_keywords_with_aliases` that discards the
    alias map and returns only the term list.
    """
    terms, _ = extract_keywords_with_aliases(posting, provider)
    return terms
