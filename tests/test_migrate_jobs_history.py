"""Jobs history migration: append-only imports, idempotency, evidence carried
across, prose attachments left alone, and the refusal that protects a volume
whose store file will not parse.

Every fixture here is synthetic. The real corpus this script was written for
carries the user's phone number and home address and is deliberately not
checked in anywhere.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import applications.store as app_store
import screening.store as screening_store
from screening.cooldown import cooldown
from scripts.migrate_jobs_history import (
    MANIFEST_NAME,
    MIGRATION_SUBDIR,
    assert_readable,
    build_attachments,
    natural_key,
    parse_cooldowns,
    parse_screening_log,
    run,
)

class _FrozenClock:
    """A stand-in for ``datetime`` that always reports the same instant.

    Two runs then compute the same backup stamp, which is how the
    refuse-to-overwrite guard is exercised without sleeping.
    """

    @staticmethod
    def now(tz=None):
        """The fixed instant every call reports."""
        return datetime(2026, 8, 14, 12, 0, 0, tzinfo=tz or timezone.utc)


RECORD = {
    "schema_version": 1,
    "application_id": "2026-08-13_acme_staff-engineer",
    "company": "Acme GmbH",
    "role": "Staff Engineer",
    "url": "https://jobs.example.com/acme/1",
    "ats": "ashby",
    "applied_date": "2026-08-13",
    "status": "confirmed",
    "capture_method": "observed",
    "gaps_disclosed": ["no Kubernetes in production"],
    "fields_submitted": [
        {"label": "Phone", "value": "+49 000", "source": "canonical"},
    ],
    "confirmation": {
        "text": "Your application has been submitted.",
        "confirmed_at": "2026-08-13T10:00:00Z",
        "evidence": "on-screen banner",
    },
    "screening": {"remote": "pass", "salary": "pass", "glassdoor": {"rating": 4.1}},
    "attachments": [{"kind": "cover_letter", "path": "scratchpad/acme_cover.pdf"}],
    "notes": "staged by the agent",
}

LOG = """# Screening record — 2026-08-14

Narrative prose that must not be parsed.

## Roles examined today and rejected, with the specific failing criterion

| Company / role | Failing criterion | Evidence |
| --- | --- | --- |
| **Nagarro — AI Engineer** | **1. Fully remote** | Office-based in Munich. |
| **Mercor, Starbridge, KDCI** | **2. German contract** | Staffing intermediaries. |
| **ClickHouse — Senior SWE** | **Not resolved — deferred** | Carry to the next run. |

**Blocked by cooldown, not examined on merit:** Langfuse and n8n
(to 2026-08-15). Acme GmbH (to 2026-11-11 — applied today; **new**).

# Screening record — 2026-08-13

Roles examined and rejected, with the specific failing criterion. Kept so the
same targets are not re-researched from scratch on the next run.

| Company / role | Failing criterion | Evidence |
|---|---|---|
| Zapier — Engineer, Applied AI | **2. German contract** | USD band only. |
| Dealfront — Senior Data Engineer | **Could not verify** | Board 404s from this machine. |

**Blocked by cooldown, not examined on merit:** RobCo, JetBrains (to 2026-09-09).
"""


@pytest.fixture()
def jobs_tree(tmp_path):
    """A minimal Jobs tree: one record, its attachment, and a screening log."""
    root = tmp_path / "Jobs"
    records = root / "applications" / "records"
    records.mkdir(parents=True)
    (records / "acme.json").write_text(json.dumps(RECORD), encoding="utf-8")
    (root / "scratchpad").mkdir()
    (root / "scratchpad" / "acme_cover.pdf").write_bytes(b"%PDF-1.4 fake")
    (root / "applications" / "SCREENING_LOG.md").write_text(LOG, encoding="utf-8")
    return root


# --- importing applications ----------------------------------------------------

def test_imports_the_record_with_its_evidence(data_dir, jobs_tree):
    run(jobs_tree, dry_run=False)
    apps = app_store.load_all()
    assert len(apps) == 1
    app = apps[0]
    assert (app.company, app.role, app.ats) == ("Acme GmbH", "Staff Engineer", "ashby")
    assert app.application_date == "2026-08-13"
    assert app.submitted is True
    assert app.capture_method == "observed"
    assert app.gaps_disclosed == ["no Kubernetes in production"]
    assert app.fields_submitted[0].label == "Phone"
    assert app.confirmation.text == "Your application has been submitted."
    assert app.screening.remote == "pass"


def test_pending_record_is_not_marked_submitted(data_dir, jobs_tree):
    record = dict(RECORD, status="pending", confirmation={})
    path = jobs_tree / "applications" / "records" / "acme.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    run(jobs_tree, dry_run=False)
    assert app_store.load_all()[0].submitted is False


def test_second_run_imports_nothing(data_dir, jobs_tree):
    run(jobs_tree, dry_run=False)
    report = run(jobs_tree, dry_run=False)
    assert len(app_store.load_all()) == 1
    assert report["applications"]["imported"] == []
    assert report["applications"]["skipped"] == ["2026-08-13_acme_staff-engineer"]


def test_existing_applications_are_left_untouched(data_dir, jobs_tree):
    existing = app_store.create({"company": "Prior Co", "application_date": "2026-07-01"})
    run(jobs_tree, dry_run=False)
    apps = app_store.load_all()
    assert len(apps) == 2
    kept = next(a for a in apps if a.id == existing.id)
    assert kept.company == "Prior Co"
    assert kept.application_date == "2026-07-01"


def test_dry_run_writes_nothing(data_dir, jobs_tree):
    report = run(jobs_tree, dry_run=True)
    assert report["records_found"] == 1
    assert app_store.load_all() == []
    assert not (data_dir / MIGRATION_SUBDIR / MANIFEST_NAME).exists()


# --- attachments ---------------------------------------------------------------

def test_attachment_is_copied_onto_the_volume(data_dir, jobs_tree):
    run(jobs_tree, dry_run=False)
    app = app_store.load_all()[0]
    name = app.attachments[0].path
    assert name == f"jobs_{app.id}_0_acme_cover.pdf"
    assert (data_dir / name).read_bytes() == b"%PDF-1.4 fake"


def test_two_attachments_sharing_a_basename_stay_separate(data_dir, jobs_tree):
    """A shared basename must not collapse two files into one on the volume."""
    (jobs_tree / "other").mkdir()
    (jobs_tree / "other" / "acme_cover.pdf").write_bytes(b"the second one")
    record = dict(
        RECORD,
        attachments=[
            {"kind": "cover_letter", "path": "scratchpad/acme_cover.pdf"},
            {"kind": "cv", "path": "other/acme_cover.pdf"},
        ],
    )
    out = build_attachments(jobs_tree, record, "abc123", dry_run=False)
    assert out[0]["path"] != out[1]["path"]
    assert (data_dir / out[0]["path"]).read_bytes() == b"%PDF-1.4 fake"
    assert (data_dir / out[1]["path"]).read_bytes() == b"the second one"


def test_prose_attachment_is_kept_verbatim(data_dir, jobs_tree):
    prose = "CV only. No cover-letter upload field was offered."
    record = dict(RECORD, attachments=[{"kind": "other", "path": prose}])
    out = build_attachments(jobs_tree, record, "abc123", dry_run=False)
    assert out == [{"kind": "other", "path": prose}]
    assert not list(data_dir.glob("jobs_*"))


def test_missing_attachment_keeps_the_original_reference(data_dir, jobs_tree):
    record = dict(RECORD, attachments=[{"kind": "cv", "path": "scratchpad/gone.pdf"}])
    out = build_attachments(jobs_tree, record, "abc123", dry_run=False)
    assert out == [{"kind": "cv", "path": "scratchpad/gone.pdf"}]


# --- the screening log ---------------------------------------------------------

def test_parses_each_dated_section(jobs_tree):
    rows = parse_screening_log(jobs_tree / "applications" / "SCREENING_LOG.md")
    dates = {r["screened_date"] for r in rows}
    assert dates == {"2026-08-14", "2026-08-13"}
    assert all(r["source"] == "imported" for r in rows)


def test_finds_the_table_when_its_marker_is_a_plain_paragraph(jobs_tree):
    """The older sections use prose, and drop the word "today", for the same
    sentence the newest section writes as a ## heading."""
    rows = parse_screening_log(jobs_tree / "applications" / "SCREENING_LOG.md")
    older = [r for r in rows if r["screened_date"] == "2026-08-13"]
    assert [r["company"] for r in older] == ["Zapier", "Dealfront"]


def test_an_unreachable_posting_is_deferred_not_rejected(jobs_tree):
    rows = parse_screening_log(jobs_tree / "applications" / "SCREENING_LOG.md")
    assert next(r for r in rows if r["company"] == "Dealfront")["verdict"] == "deferred"


def test_a_carried_over_check_is_deferred_not_rejected(jobs_tree):
    rows = parse_screening_log(jobs_tree / "applications" / "SCREENING_LOG.md")
    clickhouse = next(r for r in rows if r["company"] == "ClickHouse")
    assert clickhouse["verdict"] == "deferred"
    assert next(r for r in rows if r["company"] == "Nagarro")["verdict"] == "rejected"


def test_splits_company_from_role_on_the_em_dash(jobs_tree):
    rows = parse_screening_log(jobs_tree / "applications" / "SCREENING_LOG.md")
    nagarro = next(r for r in rows if r["company"] == "Nagarro")
    assert nagarro["role"] == "AI Engineer"
    assert nagarro["failing_criterion"] == "1. Fully remote"
    assert nagarro["reason"] == "Office-based in Munich."


def test_splits_a_multi_company_cell_with_no_role(jobs_tree):
    rows = parse_screening_log(jobs_tree / "applications" / "SCREENING_LOG.md")
    companies = {r["company"] for r in rows}
    assert {"Mercor", "Starbridge", "KDCI"} <= companies
    assert all(r["role"] == "" for r in rows if r["company"] == "Mercor")


def test_cooldown_prose_is_not_parsed_as_a_rejection(jobs_tree):
    rows = parse_screening_log(jobs_tree / "applications" / "SCREENING_LOG.md")
    assert not any("Langfuse" in r["company"] for r in rows)


# --- cooldowns -----------------------------------------------------------------

def test_cooldown_expiries_are_read_verbatim(jobs_tree):
    """The log is the only account of these dates, so they are preserved
    rather than recomputed from application_date under a different rule."""
    found = parse_cooldowns(jobs_tree / "applications" / "SCREENING_LOG.md")
    assert found == {
        "Langfuse": "2026-08-15",
        "n8n": "2026-08-15",
        "Acme GmbH": "2026-11-11",
        "RobCo": "2026-09-09",
        "JetBrains": "2026-09-09",
    }


def test_cooldown_clause_survives_a_line_wrap(jobs_tree):
    """The prose wraps mid-clause; a line-by-line read loses the pair."""
    found = parse_cooldowns(jobs_tree / "applications" / "SCREENING_LOG.md")
    assert found["Acme GmbH"] == "2026-11-11"


def test_a_migrated_company_is_reported_in_cooldown(data_dir, jobs_tree):
    """The point of the whole migration: a company known ONLY from migrated
    history must still block the agent from re-applying."""
    assert cooldown("Acme GmbH").in_cooldown is False
    run(jobs_tree, dry_run=False)
    status = cooldown("Acme GmbH")
    assert status.in_cooldown is True
    assert status.expires


def test_cooldown_rows_are_not_duplicated_on_a_second_run(data_dir, jobs_tree):
    run(jobs_tree, dry_run=False)
    first = len(screening_store.load_all())
    report = run(jobs_tree, dry_run=False)
    assert len(screening_store.load_all()) == first
    assert report["cooldowns"] == {"imported": 0, "skipped": 5}


# --- reporting rather than discarding ------------------------------------------

def test_unmapped_record_keys_are_reported(data_dir, jobs_tree):
    record = dict(RECORD, referral_source="a friend")
    path = jobs_tree / "applications" / "records" / "acme.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    report = run(jobs_tree, dry_run=False)
    assert report["unmapped_record_keys"] == {
        "2026-08-13_acme_staff-engineer": ["referral_source"]
    }


def test_a_fully_mapped_record_reports_nothing_unmapped(data_dir, jobs_tree):
    assert run(jobs_tree, dry_run=False)["unmapped_record_keys"] == {}


def test_an_unreadable_table_row_is_reported_not_dropped(data_dir, jobs_tree):
    log = jobs_tree / "applications" / "SCREENING_LOG.md"
    marker = "| Dealfront — Senior Data Engineer |"
    truncated = "| **Orphan Co** | only two cells |\n" + marker
    log.write_text(LOG.replace(marker, truncated), encoding="utf-8")
    report = run(jobs_tree, dry_run=False)
    assert any("Orphan Co" in entry for entry in report["unclassified_log_rows"])
    assert not any(s.company == "Orphan Co" for s in screening_store.load_all())


def test_screenings_are_persisted_and_not_duplicated(data_dir, jobs_tree):
    run(jobs_tree, dry_run=False)
    first = len(screening_store.load_all())
    assert first == 12  # 7 rejected/deferred rows + 5 carried-forward cooldowns
    report = run(jobs_tree, dry_run=False)
    assert len(screening_store.load_all()) == first
    assert report["screenings"] == {"imported": 0, "skipped": 7}


def test_missing_screening_log_is_not_fatal(data_dir, jobs_tree):
    (jobs_tree / "applications" / "SCREENING_LOG.md").unlink()
    report = run(jobs_tree, dry_run=False)
    assert report["screenings"]["imported"] == 0
    assert len(app_store.load_all()) == 1


# --- safety --------------------------------------------------------------------

def test_refuses_to_run_on_an_unparseable_store(data_dir, jobs_tree):
    app_store.applications_path().write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        run(jobs_tree, dry_run=False)


def test_assert_readable_passes_on_a_missing_file(tmp_path):
    assert_readable(tmp_path / "nothing.json")


def test_backs_up_the_store_before_writing(data_dir, jobs_tree):
    app_store.create({"company": "Prior Co"})
    report = run(jobs_tree, dry_run=False)
    assert report["backups"]
    backup = data_dir / MIGRATION_SUBDIR / report["backups"][0]
    assert json.loads(backup.read_text(encoding="utf-8"))[0]["company"] == "Prior Co"


def test_backups_and_manifest_are_not_reachable_by_the_download_route(
    data_dir, jobs_tree
):
    """GET /api/download/{name} serves data_dir() by bare filename and rejects
    any name with a separator, so these must not sit at the top level."""
    app_store.create({"company": "Prior Co"})
    run(jobs_tree, dry_run=False)
    top_level = {p.name for p in data_dir.iterdir() if p.is_file()}
    assert MANIFEST_NAME not in top_level
    assert not any(".bak.json" in name for name in top_level)
    assert (data_dir / MIGRATION_SUBDIR / MANIFEST_NAME).is_file()


def test_manifest_records_every_run(data_dir, jobs_tree):
    run(jobs_tree, dry_run=False)
    run(jobs_tree, dry_run=False)
    path = data_dir / MIGRATION_SUBDIR / MANIFEST_NAME
    history = json.loads(path.read_text(encoding="utf-8"))
    assert len(history) == 2
    assert history[0]["records_found"] == 1
    assert history[1]["applications"]["imported"] == []


def test_refuses_a_store_holding_json_that_is_not_a_list(data_dir, jobs_tree):
    """load_all() yields nothing from a JSON object, so a write would follow."""
    app_store.applications_path().write_text('{"records": []}', encoding="utf-8")
    with pytest.raises(SystemExit):
        run(jobs_tree, dry_run=False)


def test_refuses_to_overwrite_an_existing_backup(data_dir, jobs_tree, monkeypatch):
    app_store.create({"company": "Prior Co"})
    monkeypatch.setattr(
        "scripts.migrate_jobs_history.datetime", _FrozenClock, raising=True
    )
    run(jobs_tree, dry_run=False)
    with pytest.raises(SystemExit):
        run(jobs_tree, dry_run=False)


def test_missing_records_directory_is_an_error(data_dir, tmp_path):
    with pytest.raises(FileNotFoundError):
        run(tmp_path / "not-a-jobs-tree", dry_run=False)


# --- the dedupe key ------------------------------------------------------------

def test_natural_key_ignores_case_and_padding():
    assert natural_key(" Acme GmbH ", "Staff Engineer", "2026-08-13") == natural_key(
        "acme gmbh", "STAFF ENGINEER", "2026-08-13"
    )
