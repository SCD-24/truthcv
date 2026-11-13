"""Server-side paging for the Company research page.

A port of the web client's grouping, search and needs-review filter
(web/src/companyresearch/companyresearch.logic.ts ``groupFindingsByCompany``,
``filterCompanies``, ``openContradictionKeys`` and CompanyCard.tsx's
``companyNeedsReview``), so the page can ask for one page of companies
instead of every finding. Keep the two in step.
"""

from __future__ import annotations

from dataclasses import dataclass

from truthcv.domain.companyresearch import store as company_findings_store
from truthcv.domain.companyresearch.model import CompanyFinding, claim_key
from truthcv.infra.identity.company import company_identity_key

# Page-size bounds for GET /company-findings/companies.
COMPANIES_DEFAULT_LIMIT = 50
COMPANIES_MIN_LIMIT = 1
COMPANIES_MAX_LIMIT = 200


@dataclass
class CompanyGroup:
    """One company (every spelling sharing an identity key) and its findings."""

    company_key: str
    company: str
    findings: list[CompanyFinding]
    needs_review: bool = False


@dataclass
class CompaniesPage:
    """One page of company groups plus the effective paging values."""

    items: list[CompanyGroup]
    total: int
    limit: int
    offset: int
    companies: list[str]


def _identity(finding: CompanyFinding) -> str:
    """The grouping key: the company identity key, else the raw name."""
    return company_identity_key(finding.company) or finding.company


def _newest(findings: list[CompanyFinding]) -> CompanyFinding:
    """First finding with the greatest observed_at (ties keep the earliest)."""
    newest = findings[0]
    for f in findings:
        if f.observed_at > newest.observed_at:
            newest = f
    return newest


def group_findings_by_company(findings: list[CompanyFinding]) -> list[CompanyGroup]:
    """Group findings by identity key, preserving input order within a group.

    The display name is the most recently observed spelling; groups are
    sorted by display name, case-insensitively (stable on ties).
    """
    by_key: dict[str, list[CompanyFinding]] = {}
    for f in findings:
        by_key.setdefault(_identity(f), []).append(f)
    groups = [
        CompanyGroup(company_key=k, company=_newest(fs).company, findings=fs)
        for k, fs in by_key.items()
    ]
    return sorted(groups, key=lambda g: g.company.casefold())


def filter_companies(groups: list[CompanyGroup], query: str) -> list[CompanyGroup]:
    """Groups whose name or any finding value contains ``query``, ignoring case.

    A blank query keeps every group.
    """
    q = query.strip().lower()
    if not q:
        return groups
    return [
        g
        for g in groups
        if q in g.company.lower() or any(q in f.value.lower() for f in g.findings)
    ]


def open_contradiction_keys(groups: list[dict]) -> set[tuple[str, str]]:
    """Every (identity key, claim key) pair in an open contradiction group."""
    return {(_identity(f), claim_key(f)) for g in groups for f in g["findings"]}


def company_needs_review(group: CompanyGroup, contested: set[tuple[str, str]]) -> bool:
    """True when any claim row of ``group`` is an open contradiction."""
    return any((group.company_key, claim_key(f)) in contested for f in group.findings)


def companies_page(
    limit: int, offset: int, q: str = "", needs_review: bool = False
) -> CompaniesPage:
    """One page of company groups, filtered by ``q`` and optionally needs-review.

    Reads the findings once (newest observed_at first, as the list route
    serves them) plus the open contradictions. ``total`` counts the filtered
    groups; ``companies`` lists every display name, unfiltered. limit is
    clamped into [COMPANIES_MIN_LIMIT, COMPANIES_MAX_LIMIT] and a negative
    offset to 0; the effective values are returned to echo back.
    """
    limit = min(max(limit, COMPANIES_MIN_LIMIT), COMPANIES_MAX_LIMIT)
    offset = max(0, offset)
    findings = sorted(
        company_findings_store.load_all(), key=lambda f: f.observed_at, reverse=True
    )
    contested = open_contradiction_keys(company_findings_store.all_open_contradictions())
    groups = group_findings_by_company(findings)
    for g in groups:
        g.needs_review = company_needs_review(g, contested)
    matching = filter_companies(groups, q)
    if needs_review:
        matching = [g for g in matching if g.needs_review]
    return CompaniesPage(
        items=matching[offset : offset + limit],
        total=len(matching),
        limit=limit,
        offset=offset,
        companies=[g.company for g in groups],
    )
