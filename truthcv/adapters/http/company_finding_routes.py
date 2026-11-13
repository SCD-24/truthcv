"""Company finding routes: research findings, their contradictions and operator resolution."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from truthcv.domain.companyresearch import store as company_findings_store
from truthcv.infra.identity.company import company_identity_key
from truthcv.services import company_research_page

from .schemas import (
    CompanyFindingCreate,
    CompanyFindingModel,
    CompanyFindingResolve,
    ContradictionGroupModel,
)
from .schemas.common import _Camel

router = APIRouter()


class CompanyGroupModel(_Camel):
    """Wire shape for one company group on the Company research page."""

    company_key: str
    company: str
    findings: list[CompanyFindingModel]
    needs_review: bool


class CompanyGroupsResponse(_Camel):
    """One page of company groups, the filtered total and every company name."""

    items: list[CompanyGroupModel]
    total: int
    limit: int
    offset: int
    companies: list[str]


def _company_finding_model(f) -> CompanyFindingModel:
    """Map a stored CompanyFinding to its wire model."""
    return CompanyFindingModel(
        **f.to_dict(), company_key=company_identity_key(f.company)
    )


@router.get("/company-findings", response_model=list[CompanyFindingModel])
def list_company_findings() -> list[CompanyFindingModel]:
    """Every company research finding, newest observed_at first."""
    findings = sorted(
        company_findings_store.load_all(), key=lambda f: f.observed_at, reverse=True
    )
    return [_company_finding_model(f) for f in findings]


# Declared BEFORE /company-findings/{company}: otherwise the router binds
# "companies" as a company name and this route is unreachable.
@router.get("/company-findings/companies", response_model=CompanyGroupsResponse)
def list_company_groups(
    limit: int = company_research_page.COMPANIES_DEFAULT_LIMIT,
    offset: int = 0,
    q: str = "",
    needs_review: bool = False,
) -> CompanyGroupsResponse:
    """One page of companies with their findings, sorted by display name.

    ``q`` matches a company name or any finding value, ignoring case;
    ``needs_review`` keeps only companies with an open contradiction. limit
    is clamped and a negative offset raised to 0; effective values are echoed.
    """
    page = company_research_page.companies_page(limit, offset, q, needs_review)
    return CompanyGroupsResponse(
        items=[
            CompanyGroupModel(
                company_key=g.company_key,
                company=g.company,
                findings=[_company_finding_model(f) for f in g.findings],
                needs_review=g.needs_review,
            )
            for g in page.items
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        companies=page.companies,
    )


# Declared BEFORE /company-findings/{company}: otherwise the router binds
# "contradictions" as a company name and this route is unreachable.
@router.get(
    "/company-findings/contradictions", response_model=list[ContradictionGroupModel]
)
def list_company_finding_contradictions(
    company: str | None = None,
) -> list[ContradictionGroupModel]:
    """Open contradiction groups; narrowed to one company, or across all of them."""
    if company is not None:
        groups = company_findings_store.open_contradictions(company)
    else:
        groups = company_findings_store.all_open_contradictions()
    return [
        ContradictionGroupModel(
            claim=g["claim"],
            findings=[_company_finding_model(f) for f in g["findings"]],
        )
        for g in groups
    ]


@router.get("/company-findings/{company}", response_model=list[CompanyFindingModel])
def list_company_findings_for(company: str) -> list[CompanyFindingModel]:
    """Every finding recorded for one company."""
    return [
        _company_finding_model(f) for f in company_findings_store.for_company(company)
    ]


@router.post("/company-findings", response_model=CompanyFindingModel, status_code=201)
def create_company_finding(body: CompanyFindingCreate) -> CompanyFindingModel:
    """Record an operator-sourced company finding. Never overwrites an existing one."""
    try:
        finding = company_findings_store.record(
            company=body.company,
            claim=body.claim,
            value=body.value,
            source_url=body.source_url,
            source_class=body.source_class,
            as_of=body.as_of,
            recorded_by="operator",
            note=body.note,
            claim_label=body.claim_label,
            supersedes=body.supersedes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _company_finding_model(finding)


@router.patch("/company-findings/{finding_id}", response_model=CompanyFindingModel)
def resolve_company_finding(
    finding_id: str, body: CompanyFindingResolve
) -> CompanyFindingModel:
    """Accept or reject an existing finding. Cannot change its factual fields."""
    try:
        finding = company_findings_store.resolve(
            finding_id, body.resolution, body.note
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found.")
    return _company_finding_model(finding)
