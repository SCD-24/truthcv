"""One-shot migration: move legacy entity/glassdoor screening data into
companyresearch.

Invariant: applications.model.Screening no longer carries `entity` or
`glassdoor` — those were company-level claims with no source or as-of date.
This script moves whatever value each application's screening object still
holds for those keys into the append-only companyresearch store, tagged
source_class="unattributed" and recorded_by="import" (excluded from
contradiction detection, so the migration preserves legacy data without
blocking any auto-apply on day one), then strips the legacy keys from
applications.json.

Outcome buckets, reported per run:
  - migrated: a finding was recorded for this application's legacy value.
  - already_present: an import-sourced finding with this exact claim/value
    already exists for the company (idempotent no-op).
  - empty: the application had no legacy entity/glassdoor value to migrate.
  - manual: the application's company fails validate_company_name, so no
    finding could be recorded — needs a human to look at applications.json.

Idempotent: a second run with --apply reports zero new "migrated" entries,
because `for_company` is checked for a matching import-sourced finding before
every `record()` call.

Usage::

    python scripts/migrate_company_findings.py            # dry run, writes nothing
    python scripts/migrate_company_findings.py --apply     # migrates for real
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from applications.store import applications_path
from companyresearch import store as findings_store
from companyresearch.model import UNCITED
from storage import atomic_write_text, locked
from screening.company import validate_company_name

CLAIM_ENTITY = "employment_entity"
CLAIM_RATING = "employer_rating"


def _load_raw() -> list[dict]:
    """Applications.json as raw dicts — never through Application.from_dict,
    which no longer knows about entity/glassdoor and would drop them."""
    path = applications_path()
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


def _rating_value(glassdoor: dict) -> tuple[str, str] | None:
    """The (value, note) to record for a legacy glassdoor block, or None."""
    rating = glassdoor.get("rating", "")
    if rating not in ("", None):
        reviews = glassdoor.get("reviews", "")
        waiver = glassdoor.get("waiver_applied", False)
        note = f"reviews={reviews}, waiver_applied={waiver}"
        extra = glassdoor.get("note", "")
        if extra:
            note = f"{note}; {extra}"
        return f"{rating}", note
    note = glassdoor.get("note", "")
    if note:
        return note, ""
    return None


def classify(applications: list[dict]) -> list[dict]:
    """Pure: one plan entry per application, naming the outcome bucket."""
    plans = []
    for app in applications:
        app_id = app.get("id", "")
        company = app.get("company", "") or ""
        screening = app.get("screening") or {}
        entity = screening.get("entity", "")
        glassdoor = screening.get("glassdoor") or {}
        has_legacy = bool(entity) or bool(_rating_value(glassdoor) if glassdoor else None)
        plan = {"app_id": app_id, "company": company, "claims": []}
        if not has_legacy:
            plan["outcome"] = "empty"
            plans.append(plan)
            continue
        try:
            validate_company_name(company)
        except ValueError:
            plan["outcome"] = "manual"
            plans.append(plan)
            continue
        if entity:
            plan["claims"].append(
                {
                    "claim": CLAIM_ENTITY,
                    "value": entity,
                    "note": f"migrated from application {app_id}",
                }
            )
        rating = _rating_value(glassdoor) if glassdoor else None
        if rating is not None:
            value, extra_note = rating
            note = f"migrated from application {app_id}"
            if extra_note:
                note = f"{note}; {extra_note}"
            plan["claims"].append({"claim": CLAIM_RATING, "value": value, "note": note})
        plan["outcome"] = "planned"
        plans.append(plan)
    return plans


def _already_imported(company: str, claim: str, value: str) -> bool:
    """True when an import-sourced finding with this exact claim/value exists."""
    existing = findings_store.for_company(company)
    target = value.strip().casefold()
    return any(
        f.recorded_by == "import" and f.claim == claim and f.value.strip().casefold() == target
        for f in existing
    )


def apply_fixes(plans: list[dict]) -> dict:
    """Record findings through the store for every "planned" claim. Idempotent."""
    migrated, already_present, manual, empty = [], [], [], []
    for plan in plans:
        outcome = plan["outcome"]
        if outcome == "empty":
            empty.append(plan["app_id"])
            continue
        if outcome == "manual":
            manual.append(plan["app_id"])
            continue
        for claim in plan["claims"]:
            if _already_imported(plan["company"], claim["claim"], claim["value"]):
                already_present.append({"app_id": plan["app_id"], "claim": claim["claim"]})
                continue
            findings_store.record(
                company=plan["company"],
                claim=claim["claim"],
                value=claim["value"],
                source_url="",
                source_class=UNCITED,
                as_of="",
                recorded_by="import",
                note=claim["note"],
            )
            migrated.append({"app_id": plan["app_id"], "claim": claim["claim"]})
    return {
        "migrated": migrated,
        "already_present": already_present,
        "manual": manual,
        "empty": empty,
    }


def _strip_legacy_keys(apply_changes: bool) -> int:
    """Remove entity/glassdoor from every application's screening object.

    Writes through applications.store's own locked/atomic path — never a
    bare write. Returns the number of applications changed.
    """
    path = applications_path()
    if not apply_changes:
        raw = _load_raw()
        return sum(
            1
            for app in raw
            if "entity" in (app.get("screening") or {}) or "glassdoor" in (app.get("screening") or {})
        )
    changed = 0
    with locked(path):
        if not path.exists():
            return 0
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return 0
        for app in raw:
            screening = app.get("screening")
            if not isinstance(screening, dict):
                continue
            if "entity" in screening or "glassdoor" in screening:
                screening.pop("entity", None)
                screening.pop("glassdoor", None)
                changed += 1
        if changed:
            atomic_write_text(path, json.dumps(raw, indent=2, ensure_ascii=False))
    return changed


def back_up(path: Path, stamp: str) -> Path | None:
    """Copy a store file into a timestamped backup; None if absent."""
    if not path.exists():
        return None
    backup = path.with_name(f"{path.stem}.{stamp}.bak{path.suffix}")
    shutil.copy2(path, backup)
    return backup


def print_report(report: dict, apply_changes: bool) -> None:
    """Print the migration report, clearly labelling dry-run vs applied."""
    heading = "applied changes" if apply_changes else "dry run (nothing written)"
    print(f"=== company findings migration: {heading} ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the migration, and print the report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true", help="write changes (default is a dry run)"
    )
    args = parser.parse_args(argv)

    applications = _load_raw()
    plans = classify(applications)

    if args.apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = back_up(applications_path(), stamp)
        results = apply_fixes(plans)
        stripped = _strip_legacy_keys(apply_changes=True)
        report = {**results, "backup": str(backup) if backup else None, "applications_stripped": stripped}
    else:
        would_migrate = sum(1 for p in plans if p["outcome"] == "planned")
        would_strip = _strip_legacy_keys(apply_changes=False)
        report = {
            "would_migrate_applications": would_migrate,
            "would_strip_applications": would_strip,
            "manual": [p["app_id"] for p in plans if p["outcome"] == "manual"],
        }

    print_report(report, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
