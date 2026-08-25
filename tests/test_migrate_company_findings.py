"""Tests for scripts/migrate_company_findings.py."""

from __future__ import annotations

import json

from applications.store import applications_path
from companyresearch import store as findings_store
from scripts import migrate_company_findings as migrate


def _seed_applications(apps: list[dict]) -> None:
    applications_path().parent.mkdir(parents=True, exist_ok=True)
    applications_path().write_text(json.dumps(apps, indent=2), encoding="utf-8")


def _app(app_id, company, entity="", glassdoor=None):
    return {
        "id": app_id,
        "company": company,
        "screening": {
            "entity": entity,
            "glassdoor": glassdoor or {},
            "remote": "Berlin",
        },
    }


def test_dry_run_writes_nothing(data_dir):
    _seed_applications(
        [_app("a1", "Acme Co", entity="Acme GmbH", glassdoor={"rating": 3.3, "reviews": 17})]
    )
    exit_code = migrate.main([])
    assert exit_code == 0
    assert findings_store.load_all() == []
    raw = json.loads(applications_path().read_text(encoding="utf-8"))
    assert "entity" in raw[0]["screening"]


def test_apply_migrates_legacy_values(data_dir):
    _seed_applications(
        [
            _app(
                "a1",
                "Acme Co",
                entity="Acme GmbH, read off the Impressum",
                glassdoor={"rating": 3.3, "reviews": 17, "waiver_applied": True},
            )
        ]
    )
    migrate.main(["--apply"])
    findings = findings_store.for_company("Acme Co")
    assert len(findings) == 2
    for f in findings:
        assert f.source_class == "unattributed"
        assert f.recorded_by == "import"
    claims = {f.claim for f in findings}
    assert claims == {"employment_entity", "employer_rating"}


def test_migrated_findings_do_not_produce_open_contradictions(data_dir):
    _seed_applications(
        [
            _app("a1", "Acme Co", entity="Acme GmbH"),
            _app("a2", "Acme Co", entity="Acme Ireland Ltd"),
        ]
    )
    migrate.main(["--apply"])
    assert findings_store.open_contradictions("Acme Co") == []


def test_second_apply_run_is_a_no_op(data_dir):
    _seed_applications(
        [_app("a1", "Acme Co", entity="Acme GmbH", glassdoor={"rating": 3.3, "reviews": 17})]
    )
    migrate.main(["--apply"])
    before = len(findings_store.load_all())
    migrate.main(["--apply"])
    after = len(findings_store.load_all())
    assert before == after


def test_applications_json_no_longer_has_legacy_keys_after_apply(data_dir):
    _seed_applications(
        [_app("a1", "Acme Co", entity="Acme GmbH", glassdoor={"rating": 3.3, "reviews": 17})]
    )
    migrate.main(["--apply"])
    raw = json.loads(applications_path().read_text(encoding="utf-8"))
    assert "entity" not in raw[0]["screening"]
    assert "glassdoor" not in raw[0]["screening"]
    assert raw[0]["screening"]["remote"] == "Berlin"


def test_invalid_company_goes_to_manual_bucket_not_migrated(data_dir):
    _seed_applications([_app("a1", "n/a", entity="Some GmbH")])
    migrate.main(["--apply"])
    assert findings_store.load_all() == []
