"""Data shape for a company research finding.

A CompanyFinding records one claim about an employer — its legal/EOR entity,
an employer-review figure, or any other company-level fact — together with
where it came from and how strong that source is. Findings are append-only:
a later pass never overwrites an earlier one, because overwriting destroys
the signal that two passes disagreed. See ``companyresearch.store`` for how
that discipline is enforced and how a disagreement is surfaced.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from screening.company import validate_company_name

# Source classes, strongest first. Used to rank which side of a contradiction
# is better evidenced — never to auto-resolve one, which would defeat the
# operator gate the feature exists to provide.
SOURCE_CLASSES = (
    "audited_accounts",
    "regulatory_filing",
    "listed_bond_price",
    "company_statement",
    "press",
    "review_site",
    "unattributed",
)

# The class used for claims carried in without a citation (e.g. migrated
# legacy data). Excluded from contradiction detection: an uncited claim has
# nothing to disagree with, in either direction.
UNCITED = "unattributed"

RECORDED_BY_VALUES = ("agent", "operator", "import")
RESOLUTION_VALUES = ("", "accepted", "rejected")


def source_rank(source_class: str) -> int:
    """Position of ``source_class`` in SOURCE_CLASSES; unknown classes rank last.

    Lower is stronger. Used only for presentation/ordering — never to decide
    which side of a contradiction is "true".
    """
    if source_class in SOURCE_CLASSES:
        return SOURCE_CLASSES.index(source_class)
    return len(SOURCE_CLASSES)


def is_cited(finding: "CompanyFinding") -> bool:
    """True when ``finding`` carries a real source rather than UNCITED."""
    return finding.source_class != UNCITED


@dataclass
class CompanyFinding:
    """One immutable claim about a company, as reported by one source.

    Only ``resolution``/``resolved_at``/``resolution_note`` may ever be set on
    an existing record after it is written — every other field is fixed at
    creation. See ``companyresearch.store.record`` and ``.resolve``.
    """

    id: str = ""
    company: str = ""
    claim: str = ""
    value: str = ""
    source_url: str = ""
    source_class: str = ""
    # The date the SOURCE is dated, not the date this finding was recorded.
    # Empty means unknown and is NEVER inferred from `observed_at` — the same
    # discipline `screening.model.Screening.posted_date` uses for a posting's
    # publication date.
    as_of: str = ""
    observed_at: str = ""
    recorded_by: str = ""
    note: str = ""
    contradicts: list[str] = field(default_factory=list)
    resolution: str = ""
    resolved_at: str = ""
    resolution_note: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "CompanyFinding":
        """Build a CompanyFinding from a dict, ignoring unknown keys."""
        known = {f for f in cls.__dataclass_fields__}
        values = {k: raw[k] for k in known if k in raw}
        return cls(**values)

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON storage."""
        return {
            "id": self.id,
            "company": self.company,
            "claim": self.claim,
            "value": self.value,
            "source_url": self.source_url,
            "source_class": self.source_class,
            "as_of": self.as_of,
            "observed_at": self.observed_at,
            "recorded_by": self.recorded_by,
            "note": self.note,
            "contradicts": list(self.contradicts),
            "resolution": self.resolution,
            "resolved_at": self.resolved_at,
            "resolution_note": self.resolution_note,
        }


def new_id() -> str:
    """Short, filename-safe finding id."""
    return uuid.uuid4().hex[:12]


def validate_finding(
    company: str,
    claim: str,
    value: str,
    source_url: str,
    source_class: str,
    recorded_by: str,
) -> None:
    """Raise ValueError if this finding is not usable; otherwise return None.

    ``source_url`` is required for an agent- or operator-recorded finding —
    a company-level claim must be traceable to where it was read. It may be
    empty only for an imported, unattributed finding (legacy data that
    predates this requirement).
    """
    validate_company_name(company)
    if not claim.strip():
        raise ValueError("A claim is required — an empty claim names nothing.")
    if not value.strip():
        raise ValueError("A value is required — an empty value asserts nothing.")
    if source_class not in SOURCE_CLASSES:
        raise ValueError(
            f"Unknown source_class {source_class!r}. "
            f"Use one of: {', '.join(SOURCE_CLASSES)}."
        )
    if recorded_by not in RECORDED_BY_VALUES:
        raise ValueError(
            f"Unknown recorded_by {recorded_by!r}. "
            f"Use one of: {', '.join(RECORDED_BY_VALUES)}."
        )
    _validate_source_url(source_url, source_class, recorded_by)


def _validate_source_url(source_url: str, source_class: str, recorded_by: str) -> None:
    """Enforce the source_url requirement described in validate_finding."""
    allowed_uncited = recorded_by == "import" and source_class == UNCITED
    if allowed_uncited:
        return
    if not source_url or "://" not in source_url:
        raise ValueError(
            "A source_url is required — a company-level claim must be "
            "traceable to the page it was read from."
        )
