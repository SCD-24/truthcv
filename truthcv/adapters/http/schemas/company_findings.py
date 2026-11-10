"""Wire models for company research findings."""

from __future__ import annotations

from pydantic import Field, field_validator

from .common import _Camel


class CompanyFindingModel(_Camel):
    """Wire shape for one company research finding (response)."""

    id: str = ""
    company: str = ""
    claim: str = ""
    value: str = ""
    source_url: str = ""
    source_class: str = ""
    as_of: str = ""
    observed_at: str = ""
    recorded_by: str = ""
    note: str = ""
    claim_label: str = ""
    supersedes: str = ""
    company_key: str = ""
    contradicts: list[str] = Field(default_factory=list)
    resolution: str = ""
    resolved_at: str = ""
    resolution_note: str = ""


class CompanyFindingCreate(_Camel):
    """Client-supplied fields for a new, operator-recorded company finding."""

    company: str = ""
    claim: str = ""
    value: str = ""
    source_url: str = ""
    source_class: str = ""
    as_of: str = ""
    note: str = ""
    claim_label: str = ""
    supersedes: str = ""

    @field_validator("claim")
    @classmethod
    def _validate_claim(cls, v: str) -> str:
        from truthcv.domain.companyresearch.model import CLAIM_TYPES

        if v not in CLAIM_TYPES:
            raise ValueError(f"claim must be one of: {', '.join(CLAIM_TYPES)}")
        return v

    @field_validator("source_class")
    @classmethod
    def _validate_source_class(cls, v: str) -> str:
        from truthcv.domain.companyresearch.model import SOURCE_CLASSES

        if v not in SOURCE_CLASSES:
            raise ValueError(
                f"source_class must be one of: {', '.join(SOURCE_CLASSES)}"
            )
        return v

    @field_validator("source_url")
    @classmethod
    def _validate_source_url(cls, v: str) -> str:
        if not v or "://" not in v:
            raise ValueError("source_url is required — operator writes are never uncited")
        return v


class CompanyFindingResolve(_Camel):
    """Body for resolving (accepting/rejecting) an existing finding."""

    resolution: str = ""
    note: str = ""

    @field_validator("resolution")
    @classmethod
    def _validate_resolution(cls, v: str) -> str:
        if v not in ("", "accepted", "rejected"):
            raise ValueError("resolution must be one of: '', 'accepted', 'rejected'")
        return v


class ContradictionGroupModel(_Camel):
    """One claim with two or more disagreeing, cited findings."""

    claim: str = ""
    findings: list[CompanyFindingModel] = Field(default_factory=list)
