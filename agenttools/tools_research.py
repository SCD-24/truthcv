"""MCP tools for recording and reading sourced company research findings."""

from __future__ import annotations

from companyresearch import store


def record_company_finding(
    company: str,
    claim: str,
    value: str,
    source_url: str,
    source_class: str,
    as_of: str = "",
    note: str = "",
) -> dict:
    """Record one sourced, dated company research finding. Never overwrites.

    Args:
        company: The employing entity the claim is about.
        claim: What kind of fact this is (e.g. "employment_entity", "employer_rating").
        value: The claimed value.
        source_url: The page this was actually read from.
        source_class: One of the ranked source classes, strongest first:
            audited_accounts, regulatory_filing, listed_bond_price,
            company_statement, press, review_site, unattributed.
        as_of: The date the SOURCE is dated. Leave empty when the source
            carries no date — never infer it, never use today's date.
        note: Free-text context.

    Returns:
        The stored finding as a dict, with "contradicts" (ids of findings it
        disagrees with) and, when non-empty, a human-readable "warning".
    """
    finding = store.record(
        company=company,
        claim=claim,
        value=value,
        source_url=source_url,
        source_class=source_class,
        as_of=as_of,
        recorded_by="agent",
        note=note,
    )
    result = finding.to_dict()
    if finding.contradicts:
        result["warning"] = (
            f"This contradicts {len(finding.contradicts)} existing cited "
            f"finding(s) for the same claim — the operator must resolve this "
            f"before {company} can be applied to."
        )
    return result


def get_company_findings(company: str) -> dict:
    """Return everything recorded about a company and any open contradictions.

    A non-empty open_contradictions means the company must NOT be applied to
    until the operator resolves it.
    """
    findings = [f.to_dict() for f in store.for_company(company)]
    groups = store.open_contradictions(company)
    open_contradictions = [
        {"claim": g["claim"], "findings": [f.to_dict() for f in g["findings"]]}
        for g in groups
    ]
    return {"findings": findings, "open_contradictions": open_contradictions}
