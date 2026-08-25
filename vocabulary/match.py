"""Token/phrase-aware keyword matching for keyword coverage checks.

Two different questions are asked about the same keyword, and they need two
different notions of "match":

* An Applicant Tracking System (ATS) scans for keyword phrases *contiguously* —
  it looks for the exact phrase as a run of adjacent words. So the strict
  matcher (:func:`contains_contiguous`) models what an ATS actually sees: only
  a verbatim, adjacent phrase counts.

* A truth-coverage check asks a softer question — does the candidate's own
  history actually back this keyword? Natural phrasing like "unit and
  integration tests" plainly covers "unit tests", and penalising it would be
  wrong. So coverage uses the looser, ordered-with-gap matcher
  (:func:`contains_ordered`): the keyword's tokens must appear in order, but a
  bounded number of other tokens may sit between them.

This module deliberately does NOT import ``guardrail.validate`` — the guardrail
will later import this module, and importing it back would create a circular
import. The tokenizer here is therefore a private copy of the guardrail's
(same regex, lowering, and stripping) rather than a shared import.
"""

from __future__ import annotations

import re
from typing import Iterable

from vocabulary.synonyms import equivalent_forms

# Verdict strings returned by match_keyword, in order of decreasing strength.
EXACT = "exact"
INTERLEAVED = "interleaved"
ALIAS_ONLY = "alias-only"
ABSENT = "absent"

# Private copy of the guardrail's tokenizer shape. Kept identical on purpose so
# both modules see the same tokens, without a cross-import (see module docstring).
_TOKEN_RE = re.compile(r"\w[\w\+\.#/-]*", re.UNICODE | re.IGNORECASE)


def tokens(text: str) -> list[str]:
    """Split text into lowercased content tokens.

    Uses the same regex, lowering, and trailing-punctuation stripping as the
    guardrail's tokenizer, so tokens produced here compare equal to the ones the
    guardrail produces.

    Args:
        text: Arbitrary text (``None`` is treated as empty).

    Returns:
        The list of content tokens, in order of appearance.
    """
    return [t.lower().strip(".#/-+") for t in _TOKEN_RE.findall(text or "")]


def contains_contiguous(haystack: list[str], needle: list[str]) -> bool:
    """Whether ``needle`` appears as a contiguous run inside ``haystack``.

    This is the strict, ATS-style match: the needle tokens must be adjacent and
    in order within the haystack.

    Args:
        haystack: The token list to search within.
        needle: The token list to find as a contiguous run.

    Returns:
        True iff ``needle`` occurs as an adjacent, in-order run of ``haystack``.
        An empty ``needle`` always returns True.
    """
    if not needle:
        return True
    last = len(haystack) - len(needle)
    for start in range(last + 1):
        if haystack[start:start + len(needle)] == needle:
            return True
    return False


def contains_ordered(haystack: list[str], needle: list[str], max_gap: int = 3) -> bool:
    """Whether ``needle``'s tokens appear in ``haystack`` in order, gap-bounded.

    This is the loose, coverage-style match: every needle token must be found in
    order, but up to ``max_gap`` haystack tokens may sit between the position of
    one matched needle token and the next one's match. Implemented as a single
    forward scan with a pointer into the haystack.

    Args:
        haystack: The token list to search within.
        needle: The token list whose tokens must appear in order.
        max_gap: The maximum number of haystack tokens allowed between one
            matched needle token and the next.

    Returns:
        True iff every token of ``needle`` is found in order with each step's
        gap no greater than ``max_gap``. An empty ``needle`` returns True.
    """
    if not needle:
        return True
    pos = 0  # next haystack index to consider
    for i, token in enumerate(needle):
        gap = 0
        while pos < len(haystack) and haystack[pos] != token:
            if i > 0 and gap >= max_gap:
                return False
            pos += 1
            gap += 1
        if pos >= len(haystack):
            return False
        pos += 1  # consume the matched token
    return True


def _matches_any_form(text_tokens: list[str], forms: Iterable[str]) -> bool:
    """Whether any alias form matches ``text_tokens``, strictly or loosely.

    Args:
        text_tokens: The tokenized text to match against.
        forms: Candidate alias strings to try.

    Returns:
        True iff some form's tokens are found in ``text_tokens`` by either a
        contiguous or an ordered match.
    """
    for form in forms:
        form_tokens = tokens(form)
        if not form_tokens:
            continue
        if contains_contiguous(text_tokens, form_tokens):
            return True
        if contains_ordered(text_tokens, form_tokens):
            return True
    return False


def match_keyword(keyword: str, text: str, aliases: Iterable[str] = ()) -> str:
    """Classify how strongly ``text`` matches ``keyword``.

    Resolution order, strongest first:

    1. Contiguous (ATS-style) match of the keyword -> :data:`EXACT`.
    2. Otherwise an ordered, gap-bounded match of the keyword ->
       :data:`INTERLEAVED`.
    3. Otherwise, if any alias form — the caller-supplied ``aliases`` plus the
       known-equivalent forms from :func:`vocabulary.synonyms.equivalent_forms`
       — matches contiguously or in order -> :data:`ALIAS_ONLY`.
    4. Otherwise -> :data:`ABSENT`.

    Args:
        keyword: The keyword or keyword phrase to look for.
        text: The text to search within.
        aliases: Extra equivalent forms to accept, beyond the synonym store.

    Returns:
        One of :data:`EXACT`, :data:`INTERLEAVED`, :data:`ALIAS_ONLY`, or
        :data:`ABSENT`.
    """
    keyword_tokens = tokens(keyword)
    text_tokens = tokens(text)
    if contains_contiguous(text_tokens, keyword_tokens):
        return EXACT
    if contains_ordered(text_tokens, keyword_tokens):
        return INTERLEAVED
    forms = list(aliases) + list(equivalent_forms(keyword))
    if _matches_any_form(text_tokens, forms):
        return ALIAS_ONLY
    return ABSENT
