"""Persistence for company research findings against the ./data volume.

A later pass never overwrites an earlier finding — the whole feature rests on
that rule, because overwriting destroys the signal that two passes disagreed.
``record`` only ever appends; the sole mutation this module permits on an
existing record is ``resolve``, which stamps an operator's accept/reject
decision without touching the finding's factual fields.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from storage import atomic_write_text, locked
from screening.company import company_identity_key
from storage import data_dir

from .model import (
    RESOLUTION_VALUES,
    CompanyFinding,
    is_cited,
    new_id,
    source_rank,
    validate_finding,
)


def findings_path() -> Path:
    """Where company_findings.json lives on the data volume."""
    return data_dir() / "company_findings.json"


def _now() -> str:
    """UTC ISO-8601 timestamp; single source for observed_at/resolved_at."""
    return datetime.now(timezone.utc).isoformat()


def load_all() -> list[CompanyFinding]:
    """Every finding; empty list if the file is missing or invalid.

    Fails safe (returns []) on a missing file, malformed JSON, or a payload
    that isn't a list, so a hand-edited or partially written file never
    crashes the app on startup. Unlocked: reads may race a writer's rename,
    which is atomic, so a reader sees either the old or the new file whole.
    """
    p = findings_path()
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    return [CompanyFinding.from_dict(item) for item in raw if isinstance(item, dict)]


def _write_all(items: list[CompanyFinding]) -> None:
    """Persist the full list to company_findings.json.

    Callers must already hold ``locked(findings_path())`` — this writes the
    list it is given and does no reconciliation, so an unguarded caller
    overwrites whatever another writer stored since it loaded.
    """
    atomic_write_text(
        findings_path(),
        json.dumps([f.to_dict() for f in items], indent=2, ensure_ascii=False),
    )


def get(finding_id: str) -> CompanyFinding | None:
    """The finding with this id, or None. Unlocked, like load_all."""
    return next((f for f in load_all() if f.id == finding_id), None)


def _key(company: str) -> str:
    """Normalized key used to match findings to the same company.

    Delegates to ``screening.company.company_identity_key``, the single
    shared company-identity key, so a legal-entity suffix does not split one
    employer's research across two buckets: findings recorded against
    "RobCo GmbH" are matched (and contradiction-checked) against those
    recorded as "RobCo".
    """
    return company_identity_key(company)


def for_company(company: str) -> list[CompanyFinding]:
    """Every finding for ``company``, sorted by observed_at then id."""
    key = _key(company)
    matches = [f for f in load_all() if _key(f.company) == key]
    return sorted(matches, key=lambda f: (f.observed_at, f.id))


def _values_differ(a: str, b: str) -> bool:
    """True when two claim values differ after normalizing for comparison."""
    return a.strip().casefold() != b.strip().casefold()


def _contradiction_ids(existing: list[CompanyFinding], claim: str, value: str) -> list[str]:
    """Ids of existing cited, non-rejected findings that disagree with `value`."""
    ids = []
    for f in existing:
        if f.claim != claim:
            continue
        if not is_cited(f):
            continue
        if f.resolution == "rejected":
            continue
        if _values_differ(f.value, value):
            ids.append(f.id)
    return ids


def record(
    company: str,
    claim: str,
    value: str,
    source_url: str = "",
    source_class: str = "",
    as_of: str = "",
    recorded_by: str = "agent",
    note: str = "",
) -> CompanyFinding:
    """Append a new finding. Never mutates or removes an existing one.

    Raises ValueError (storing nothing) when the finding fails validation. An
    uncited finding (source_class == "unattributed") never contradicts and is
    never contradicted — only cited findings participate in contradiction
    detection, so migrated legacy data does not retroactively block anything.
    """
    validate_finding(company, claim, value, source_url, source_class, recorded_by)
    finding = CompanyFinding(
        id=new_id(),
        company=company,
        claim=claim,
        value=value,
        source_url=source_url,
        source_class=source_class,
        as_of=as_of,
        observed_at=_now(),
        recorded_by=recorded_by,
        note=note,
    )
    with locked(findings_path()):
        items = load_all()
        if is_cited(finding):
            key = _key(company)
            same_company = [f for f in items if _key(f.company) == key]
            finding.contradicts = _contradiction_ids(same_company, claim, value)
        items.append(finding)
        _write_all(items)
    return finding


def resolve(finding_id: str, resolution: str, note: str = "") -> CompanyFinding | None:
    """Stamp an operator's accept/reject decision on an existing finding.

    The only mutation this store permits: value, source_url, source_class and
    as_of stay immutable once written. Returns None for an unknown id; raises
    ValueError for an unknown resolution.
    """
    if resolution not in RESOLUTION_VALUES:
        raise ValueError(
            f"Unknown resolution {resolution!r}. Use one of: {', '.join(RESOLUTION_VALUES)}."
        )
    with locked(findings_path()):
        items = load_all()
        finding = next((f for f in items if f.id == finding_id), None)
        if finding is None:
            return None
        finding.resolution = resolution
        finding.resolved_at = _now()
        finding.resolution_note = note
        _write_all(items)
        return finding


def open_contradictions(company: str) -> list[dict]:
    """Open contradiction groups for ``company``: cited claims with >=2 values.

    Each entry is {"claim": str, "findings": [CompanyFinding, ...]}, findings
    ordered strongest source first then most recently observed. A rejected
    finding is excluded, so resolving one side clears the group. Returns []
    for a clean company.
    """
    cited = [f for f in for_company(company) if is_cited(f) and f.resolution != "rejected"]
    by_claim: dict[str, list[CompanyFinding]] = {}
    for f in cited:
        by_claim.setdefault(f.claim, []).append(f)
    groups = []
    for claim, findings in by_claim.items():
        values = {f.value.strip().casefold() for f in findings}
        if len(values) < 2:
            continue
        # Stable sort: most recently observed first, then strongest source
        # first — the second sort's ties keep the first sort's ordering.
        ordered = sorted(findings, key=lambda f: f.observed_at, reverse=True)
        ordered.sort(key=lambda f: source_rank(f.source_class))
        groups.append({"claim": claim, "findings": ordered})
    return groups
