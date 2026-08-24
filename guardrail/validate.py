"""Deterministic, scoped token-diff validation of a draft against truth.

Every content token in the draft must be traceable to a truth token — but now
*in context*: a token in a job's draft block must appear in that same job's truth
facts (role/company/dates/bullets), not merely somewhere in the whole profile.
Skills are allowed globally. This is what stops a date (or any fact) from one job
silently attaching to another.

Common English stopwords and pure formatting/punctuation are always allowed so
light rephrasing ("Built" -> "Delivered a") does not trip the guardrail. No LLM
dependency — the same input always yields the same result.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable

from truth.store import data_dir

# Connective/function words that carry no factual content. Rephrasing may freely
# introduce these; they are never treated as claims.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on",
    "or", "the", "to", "with", "using", "used", "via", "per", "across", "over",
    "within", "including", "led", "build", "built", "building", "delivered",
    "deliver", "developed", "develop", "created", "create", "designed", "design",
    "implemented", "implement", "managed", "manage", "owned", "own", "drove",
    "drive", "responsible", "worked", "work", "helped", "help", "supported",
    "support", "improved", "improve", "increased", "reduced", "enabled", "ensured",
    "provided", "maintained", "collaborated", "team", "teams", "project",
    "projects", "experience", "years", "year", "strong", "proven", "skilled",
    "is", "was", "are", "were", "be", "been", "that", "this", "which", "who",
    "our", "their", "his", "her", "its", "it", "s",
})


# Per-data_dir cache of the loaded stopword set; initialised lazily by
# _stopwords() so import order never touches the filesystem.
_stopwords_cache: tuple[str, frozenset[str]] | None = None


def _stopwords() -> frozenset[str]:
    """The effective stopword set: built-ins plus any operator-supplied list.

    Cached per data_dir so the file is read once per process.
    """
    global _stopwords_cache
    key = str(data_dir())
    if _stopwords_cache is None or _stopwords_cache[0] != key:
        _stopwords_cache = (key, _load_stopwords())
    return _stopwords_cache[1]


def _load_stopwords() -> frozenset[str]:
    """Built-in English stopwords merged with an operator-supplied list.

    A CV in another language would otherwise have every connective flagged as
    an unverifiable claim and blocked at render, so the operator can supply
    extra stopwords in data/stopwords.txt (one word per line; '#' starts a
    comment). A missing OR unreadable file means built-ins only — the
    guardrail degrades to today's exact behaviour rather than failing a run.
    """
    words = set(_STOPWORDS)
    path = data_dir() / "stopwords.txt"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return frozenset(words)
    except OSError as exc:
        logging.getLogger(__name__).warning("Could not read %s (%s); using built-in stopwords only", path, exc)
        return frozenset(words)
    for line in lines:
        word = line.strip()
        if word and not word.startswith("#"):
            # Tokenize like the guardrail does, then take the whole token(s):
            # a stopword must compare equal to what _tokenize produces.
            words.update(tok for tok in _tokenize(word) if tok)
            if not _tokenize(word):
                words.add(word.casefold())
    return frozenset(words)

# Unicode-aware: \w under Python's re matches [a-zA-Z0-9_] plus every Unicode
# word character (letters with diacritics, non-Latin scripts), so 'Müller' or
# 'Škoda' tokenize as single tokens instead of shattering at the accented
# character. This only widens what counts as one token — a token that used to
# match still matches, so no verdict can flip from blocked to allowed.
_TOKEN_RE = re.compile(r"\w[\w\+\.#/-]*", re.UNICODE | re.IGNORECASE)


@dataclass
class BlockedClaim:
    """A single draft text (a bullet/line) that tripped the guardrail, with the
    specific untraceable tokens and the scope it belongs to. This lets callers
    present a whole-claim approve/deny instead of loose, contextless words."""

    scope_id: str
    text: str
    tokens: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {"scopeId": self.scope_id, "text": self.text, "tokens": list(self.tokens)}


@dataclass
class ValidationResult:
    ok: bool
    unverifiable: list[str] = field(default_factory=list)
    blocked_claims: list[BlockedClaim] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "unverifiable": list(self.unverifiable),
            "blockedClaims": [c.to_dict() for c in self.blocked_claims],
        }


@dataclass
class Scope:
    """One validation scope: draft `texts` that may only draw on `allowed`.

    e.g. a job's rendered role/company/dates/bullets, scoped to that same job's
    truth facts. `global_values` on validate() (skills) are allowed in every scope.
    An optional `id` labels the scope so blocked claims can be traced back to the
    draft block (e.g. experience) they came from.
    """

    texts: list[str] = field(default_factory=list)
    allowed: list[str] = field(default_factory=list)
    id: str = ""


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip trailing punctuation, split into content tokens."""
    return [t.lower().strip(".#/-+") for t in _TOKEN_RE.findall(text or "")]


def _truth_tokens(values: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        tokens.update(_tokenize(value))
    return tokens


def validate(scopes: Iterable[Scope], global_values: Iterable[str] = ()) -> ValidationResult:
    """Return ok + the list of unverifiable draft tokens.

    Each scope's draft texts are validated against that scope's own allowed truth
    values plus `global_values` (skills, allowed everywhere). A token is verifiable
    if it is a stopword or appears verbatim (post-tokenization) in that scope's
    allowed set. A token that only exists in a *different* scope is unverifiable —
    that is the per-experience invariant.
    """
    global_tokens = _truth_tokens(global_values)
    unverifiable: list[str] = []
    seen: set[str] = set()
    blocked: list[BlockedClaim] = []

    for scope in scopes:
        allowed = _truth_tokens(scope.allowed) | global_tokens
        for text in scope.texts:
            bad = _untraceable_tokens(text, allowed)
            if not bad:
                continue
            # Group flagged tokens under their source text so a whole claim can
            # be approved/denied. The flat list stays deduped for back-compat.
            blocked.append(BlockedClaim(scope_id=scope.id, text=text, tokens=bad))
            for tok in bad:
                if tok not in seen:
                    seen.add(tok)
                    unverifiable.append(tok)

    return ValidationResult(
        ok=(len(blocked) == 0), unverifiable=unverifiable, blocked_claims=blocked
    )


def _untraceable_tokens(text: str, allowed: set[str]) -> list[str]:
    """The content tokens in one draft text that aren't traceable to `allowed`."""
    out: list[str] = []
    for tok in _tokenize(text):
        if not tok or tok in _stopwords() or tok in allowed:
            continue
        if tok not in out:
            out.append(tok)
    return out
