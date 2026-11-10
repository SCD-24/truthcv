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


SCORE_SENDER_DOMAIN = 6
SCORE_ATS_PLATFORM = 4
SCORE_COMPANY = 2
SCORE_ROLE = 2
HIGH_THRESHOLD = 8
MEDIUM_THRESHOLD = 6
MIN_ROLE_LEN = 3

# Hiring-platform (ATS) family -> sender/host suffixes. personio and recruitee are best guesses.
_ATS_FAMILIES: dict[str, tuple[str, ...]] = {
    "greenhouse": ("greenhouse.io", "greenhouse-mail.io"),
    "lever": ("lever.co",),
    "workable": ("workable.com", "workablemail.com"),
    "smartrecruiters": ("smartrecruiters.com",),
    "teamtailor": ("teamtailor.com", "teamtailor-mail.com"),
    "join": ("join.com",),
    "ashby": ("ashbyhq.com",),
    "personio": ("personio.de", "personio.com"),
    "recruitee": ("recruitee.com",),
}


def _ats_family(host: str) -> str:
    """ATS family whose suffix equals or parents the host, or "" when none."""
    for family, suffixes in _ATS_FAMILIES.items():
        if any(host == s or host.endswith(f".{s}") for s in suffixes):
            return family
    return ""


def _app_hosts(app) -> set[str]:
    """Raw hosts of the application's website and application_url."""
    hosts = set(_domain_parts(getattr(app, "website", "")))
    hosts.update(_domain_parts(getattr(app, "application_url", "")))
    return {h for h in hosts if h}


def _app_domains(app) -> set[str]:
    domains = _app_hosts(app)
    token = _company_token(getattr(app, "company", ""))
    if token:
        domains.add(token)
    return domains


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


def _score_domain(app, domain: str, family: str) -> tuple[int, list[str]]:
    """Sender-domain (+6, ATS hosts excluded) or same-ATS-platform (+4) score."""
    hosts = _app_hosts(app)
    token = _company_token(getattr(app, "company", ""))
    domains = {h for h in hosts if not _ats_family(h)} | ({token} if token else set())
    if domain and any(_domain_matches(d, domain) for d in domains):
        return SCORE_SENDER_DOMAIN, [f"sender domain matched {domain}"]
    if family and any(_ats_family(h) == family for h in hosts):
        return SCORE_ATS_PLATFORM, [f"hiring platform matched {family}"]
    return 0, []


def _score_text(app, text: str) -> tuple[int, list[str], int]:
    """Company/role keyword score, evidence, and the number of keyword kinds matched."""
    score, hits = 0, 0
    evidence: list[str] = []
    company = _company_token(getattr(app, "company", ""))
    contains = _contains_word if _is_short_token(company) else _contains_term
    if contains(text, company):
        score += SCORE_COMPANY
        hits += 1
        evidence.append(f"company keyword matched {company}")
    role = _normalize(getattr(app, "role", ""))
    if len(role) >= MIN_ROLE_LEN and _contains_term(text, role):
        score += SCORE_ROLE
        hits += 1
        evidence.append("role keyword matched")
    return score, evidence, hits


def _confidence(score: int, both_matched: bool) -> str:
    """high/medium by threshold; company+role together floor at medium."""
    if score >= HIGH_THRESHOLD:
        return "high"
    if score >= MEDIUM_THRESHOLD or both_matched:
        return "medium"
    return "low"


def _score_app(app, domain: str, family: str, text: str) -> tuple[int, MatchResult] | None:
    """Score one application against a message; None when nothing matched."""
    score, evidence = _score_domain(app, domain, family)
    text_score, text_evidence, hits = _score_text(app, text)
    score += text_score
    if score <= 0:
        return None
    label = getattr(app, "company", "") or "Application"
    if getattr(app, "role", ""):
        label = f"{label} — {app.role}"
    confidence = _confidence(score, hits == 2)
    return score, MatchResult(app.id, label, confidence, evidence + text_evidence)


def match_message(applications: list, *, sender: str, subject: str, snippet: str) -> MatchResult | None:
    """Best-matching application for a message, or None when none or a tie."""
    domain = sender_domain(sender)
    family = _ats_family(domain)
    text = _normalize(f"{subject} {snippet}")
    results = (_score_app(app, domain, family, text) for app in applications)
    scored = [r for r in results if r is not None]
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]
