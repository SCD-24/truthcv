"""Tests for companyresearch/claim_migration.py and scripts/migrate_company_claims.py.

The module holds the migration logic (incl. startup ``migrate_claims_if_needed``);
the script is a thin CLI (dry run / --apply) over it.
"""

from __future__ import annotations

import json

from companyresearch import store as findings_store
from companyresearch.claim_migration import build_report, migrate_claims_if_needed
from scripts import migrate_company_claims as migrate


def _finding(fid, claim, value="v", company="Acme Co", source_class="press", observed="2026-01-01"):
    return {
        "id": fid,
        "company": company,
        "claim": claim,
        "value": value,
        "source_url": "https://x.example",
        "source_class": source_class,
        "observed_at": observed,
        "recorded_by": "agent",
    }


def _seed(items):
    p = findings_store.findings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items), encoding="utf-8")


def _raw():
    return json.loads(findings_store.findings_path().read_text(encoding="utf-8"))


def test_dry_run_writes_nothing(data_dir, capsys):
    _seed([_finding("a", "Glassdoor rating")])
    before = findings_store.findings_path().read_text(encoding="utf-8")
    assert migrate.main([]) == 0
    assert findings_store.findings_path().read_text(encoding="utf-8") == before
    assert "employer_rating" in capsys.readouterr().out
    assert not list(findings_store.findings_path().parent.glob("*.bak*"))


def test_apply_maps_and_preserves_label(data_dir):
    _seed([
        _finding("a", "Glassdoor Rating"),
        _finding("b", "Employing entity"),
        _finding("c", "German presence"),
        _finding("d", "Kununu review count"),
    ])
    migrate.main(["--apply"])
    by_id = {f["id"]: f for f in _raw()}
    assert by_id["a"]["claim"] == "employer_rating" and by_id["a"]["claim_label"] == "Glassdoor Rating"
    assert by_id["b"]["claim"] == "employment_entity"
    assert by_id["c"]["claim"] == "employment_entity"
    assert by_id["d"]["claim"] == "employer_rating"


def test_second_run_is_noop(data_dir):
    _seed([_finding("a", "EOR")])
    migrate.main(["--apply"])
    first = findings_store.findings_path().read_text(encoding="utf-8")
    report = build_report(_raw())
    assert report["to_map"] == 0
    migrate.main(["--apply"])
    assert findings_store.findings_path().read_text(encoding="utf-8") == first


def test_unmatched_claim_falls_back_to_other(data_dir):
    _seed([_finding("a", "Funding stage")])
    migrate.main(["--apply"])
    item = _raw()[0]
    assert item["claim"] == "other" and item["claim_label"] == "Funding stage"


def test_distinct_other_labels_produce_no_contradiction(data_dir):
    _seed([
        _finding("a", "Funding stage", value="Series B"),
        _finding("b", "Headquarters", value="Berlin"),
    ])
    report = build_report(_raw())
    assert report["new_contradictions"] == []


def test_apply_creates_backup(data_dir, capsys):
    _seed([_finding("a", "EOR")])
    migrate.main(["--apply"])
    backups = list(findings_store.findings_path().parent.glob("company_findings.*.bak.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))[0]["claim"] == "EOR"


def _backups():
    return list(findings_store.findings_path().parent.glob("*.bak*"))


def test_startup_migration_noop_when_all_typed(data_dir):
    _seed([_finding("a", "employer_rating"), _finding("b", "employment_entity")])
    path = findings_store.findings_path()
    before = path.read_bytes()
    assert migrate_claims_if_needed() is None
    assert path.read_bytes() == before
    assert sorted(p.name for p in data_dir.iterdir()) == ["company_findings.json"]


def test_startup_migration_no_file_creates_nothing(data_dir):
    assert migrate_claims_if_needed() is None
    assert list(data_dir.iterdir()) == []


def test_startup_migration_maps_legacy_and_backs_up(data_dir):
    _seed([_finding("a", "EOR")])
    report = migrate_claims_if_needed()
    assert report["to_map"] == 1
    assert report["backup"] is not None
    from pathlib import Path
    backup = Path(report["backup"])
    assert backup.exists()
    assert json.loads(backup.read_text(encoding="utf-8"))[0]["claim"] == "EOR"
    item = _raw()[0]
    assert item["claim"] == "employment_entity" and item["claim_label"] == "EOR"


def test_startup_migration_second_call_is_noop(data_dir):
    _seed([_finding("a", "EOR")])
    assert migrate_claims_if_needed() is not None
    count = len(_backups())
    assert migrate_claims_if_needed() is None
    assert len(_backups()) == count


def test_contradiction_preview_reports_new_groups(data_dir):
    _seed([
        _finding("a", "Employing entity", value="Acme GmbH"),
        _finding("b", "EOR", value="Acme Ltd", source_class="company_statement"),
    ])
    report = build_report(_raw())
    assert len(report["new_contradictions"]) == 1
    assert report["new_contradictions"][0]["claim"] == "employment_entity"
    assert report["mapped_counts"]["employment_entity"] == 2
