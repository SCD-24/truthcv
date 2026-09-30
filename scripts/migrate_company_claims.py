"""One-off migration: map free-text company finding claims onto CLAIM_TYPES.

Company findings used to carry any free-text ``claim``. Duplicates that meant
the same thing ("Employing entity", "EOR", ...) never matched, so contradiction
detection silently missed them. This script rewrites every stored finding whose
claim is not in ``companyresearch.model.CLAIM_TYPES``: the original text moves
to ``claim_label`` and ``claim`` becomes one of the fixed types, chosen by a
case-insensitive keyword match:

  - contains "rating" or "review"                         -> employer_rating
  - contains entity/eor/hire/hiring/employ/german presence -> employment_entity
  - anything else                                         -> other

DOCUMENTED EXCEPTION to the append-only rule: this rewrites
company_findings.json in place, once, under ``locked`` + ``atomic_write_text``,
after a timestamped backup. Nothing else in the codebase may do this.

Idempotent: findings whose claim is already a claim type are left untouched,
so a second ``--apply`` changes nothing.

The report lists per-type counts, each original -> type mapping, and companies
that would newly have an open contradiction after mapping (computed with the
store's own contradiction logic).

Usage::

    python scripts/migrate_company_claims.py            # dry run, writes nothing
    python scripts/migrate_company_claims.py --apply     # rewrites for real
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from companyresearch import store as findings_store
from companyresearch.model import CLAIM_TYPES, CompanyFinding
from scripts.migrate_company_findings import back_up
from storage import atomic_write_text, locked

_RATING_WORDS = ("rating", "review")
_ENTITY_WORDS = ("entity", "eor", "hire", "hiring", "employ", "german presence")


def map_claim(text: str) -> str:
    """Map a free-text claim onto a claim type by case-insensitive keywords."""
    lowered = text.casefold()
    if any(w in lowered for w in _RATING_WORDS):
        return "employer_rating"
    if any(w in lowered for w in _ENTITY_WORDS):
        return "employment_entity"
    return "other"


def _load_raw() -> list:
    """company_findings.json as raw JSON; [] when missing or malformed."""
    path = findings_store.findings_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return raw if isinstance(raw, list) else []


def migrate_items(raw: list) -> tuple[list, list[dict]]:
    """Pure: return (new raw list, mappings) with non-enum claims remapped."""
    out, mappings = [], []
    for item in raw:
        if not isinstance(item, dict) or item.get("claim") in CLAIM_TYPES:
            out.append(item)
            continue
        original = str(item.get("claim", ""))
        mapped = map_claim(original)
        out.append({**item, "claim": mapped, "claim_label": original})
        mappings.append({"id": item.get("id", ""), "original": original, "mapped": mapped})
    return out, mappings


def _contradiction_pairs(raw: list) -> set[tuple[str, str]]:
    """(company key, claim) pairs with an open contradiction, via store logic."""
    by_company: dict[str, list[CompanyFinding]] = {}
    for item in raw:
        if isinstance(item, dict):
            f = CompanyFinding.from_dict(item)
            by_company.setdefault(findings_store._key(f.company), []).append(f)
    return {
        (key, g["claim"])
        for key, fs in by_company.items()
        for g in findings_store._open_contradictions_from(fs)
    }


def build_report(raw: list) -> dict:
    """Pure: the migration report for ``raw`` (per-type counts, mappings, new contradictions)."""
    new_raw, mappings = migrate_items(raw)
    counts = {t: 0 for t in CLAIM_TYPES}
    for m in mappings:
        counts[m["mapped"]] += 1
    new_pairs = sorted(_contradiction_pairs(new_raw) - _contradiction_pairs(raw))
    return {
        "total_findings": len(raw),
        "to_map": len(mappings),
        "mapped_counts": counts,
        "mappings": [f"{m['original']} -> {m['mapped']}" for m in mappings],
        "new_contradictions": [{"company_key": k, "claim": c} for k, c in new_pairs],
    }


def apply_migration() -> dict:
    """Back up, then rewrite company_findings.json in place under the lock."""
    path = findings_store.findings_path()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with locked(path):
        raw = _load_raw()
        report = build_report(raw)
        if not report["to_map"]:
            return {**report, "backup": None}
        backup = back_up(path, stamp)
        new_raw, _ = migrate_items(raw)
        atomic_write_text(path, json.dumps(new_raw, indent=2, ensure_ascii=False))
    return {**report, "backup": str(backup) if backup else None}


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the migration (dry run by default), print JSON."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    args = parser.parse_args(argv)
    if args.apply:
        report = apply_migration()
        heading = "applied changes"
    else:
        report = build_report(_load_raw())
        heading = "dry run (nothing written)"
    print(f"=== company claims migration: {heading} ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
