from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import parseaddr
from urllib.parse import urlparse


@dataclass
class MatchResult:
    application_id: str
    application_label: str
    confidence: str
    evidence: list[str]


def _sender_email(sender: str) -> str:
    return parseaddr(sender)[1].strip().lower()


def sender_domain(sender: str) -> str:
    email = _sender_email(sender)
    return email.partition("@")[2]


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _domain_parts(value: str) -> list[str]:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.netloc or parsed.path).lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return [host] if host else []


MIN_COMPANY_TOKEN_LEN = 3

_COMPANY_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "und", "of", "for", "der", "die", "das", "le", "la", "el", "de",
        "von", "van", "at", "in", "on",
        "gmbh", "mbh", "ag", "se", "kg", "ug", "ltd", "limited", "inc", "llc", "corp", "corporation",
        "co", "plc", "bv", "nv", "sa", "sas", "srl", "spa", "oy", "ab", "as", "aps", "kft", "pty",
        "group", "gruppe", "holding", "holdings", "company", "international", "germany", "deutschland",
        "europe", "global", "technologies", "technology", "solutions", "services", "systems",
        "digital", "labs", "team", "hiring", "careers", "jobs",
    }
)


# Distinctive short names MIN_COMPANY_TOKEN_LEN would otherwise discard.
_SHORT_COMPANY_ALLOWLIST = frozenset({"hp", "ey", "bp", "ge", "3m", "o2", "vw", "db"})


def _company_token(company: str) -> str:
    """First distinctive word of a company name, or "" when none exists.

    Allowlisted short names (e.g. "EY", "HP") are returned as-is. Otherwise
    skips stopwords (articles, legal forms, generic words) and tokens shorter
    than MIN_COMPANY_TOKEN_LEN, so "The Quality Group GmbH" yields "quality"
    rather than "the", which would substring-match nearly any message.
    """
    for token in _normalize(company).split():
        if token in _SHORT_COMPANY_ALLOWLIST:
            return token
        if token not in _COMPANY_STOPWORDS and len(token) >= MIN_COMPANY_TOKEN_LEN:
            return token
    return ""


def _app_domains(app) -> set[str]:
    domains = set(_domain_parts(getattr(app, "website", "")))
    domains.update(_domain_parts(getattr(app, "application_url", "")))
    token = _company_token(getattr(app, "company", ""))
    if token:
        domains.add(token)
    return {d for d in domains if d}


def _contains_term(haystack: str, needle: str) -> bool:
    if not haystack or not needle:
        return False
    return needle in haystack


def _is_short_token(token: str) -> bool:
    """True when the token is shorter than MIN_COMPANY_TOKEN_LEN."""
    return len(token) < MIN_COMPANY_TOKEN_LEN


def _contains_word(haystack: str, needle: str) -> bool:
    """True when needle appears in the normalized haystack as a whole word."""
    if not haystack or not needle:
        return False
    return f" {needle} " in f" {haystack} "


def _domain_matches(d: str, domain: str) -> bool:
    """Match an app domain term to a sender domain; short terms need an exact label."""
    if _is_short_token(d):
        return d in domain.split(".")
    return d == domain or d in domain or domain in d


def match_message(applications: list, *, sender: str, subject: str, snippet: str) -> MatchResult | None:
    domain = sender_domain(sender)
    text = _normalize(f"{subject} {snippet}")
    scored: list[tuple[int, MatchResult]] = []
    for app in applications:
        score = 0
        evidence: list[str] = []
        domains = _app_domains(app)
        if domain and any(_domain_matches(d, domain) for d in domains):
            score += 6
            evidence.append(f"sender domain matched {domain}")
        company = _company_token(getattr(app, "company", ""))
        contains = _contains_word if _is_short_token(company) else _contains_term
        if contains(text, company):
            score += 2
            evidence.append(f"company keyword matched {company}")
        role = _normalize(getattr(app, "role", ""))
        if role and len(role) > 2 and _contains_term(text, role):
            score += 2
            evidence.append("role keyword matched")
        if score <= 0:
            continue
        confidence = "high" if score >= 8 else "medium" if score >= 6 else "low"
        label = getattr(app, "company", "") or "Application"
        if getattr(app, "role", ""):
            label = f"{label} — {app.role}"
        scored.append(
            (
                score,
                MatchResult(
                    application_id=app.id,
                    application_label=label,
                    confidence=confidence,
                    evidence=evidence,
                ),
            )
        )
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]
