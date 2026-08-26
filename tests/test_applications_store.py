"""Application Tracker store: CRUD, atomic persistence, and owned documents."""

from __future__ import annotations

from datetime import date

import applications
from applications.store import (
    applications_path,
    cover_letter_filenames,
    create_for_screening,
    cv_filenames,
)
from truth.store import data_dir


def test_empty_when_no_file(data_dir):
    assert applications.load_all() == []


def test_create_and_load_round_trip(data_dir):
    app = applications.create(
        {
            "company": "Vandelay",
            "website": "https://www.vandelay.example/en/",
            "application_url": "N/A",
            "submitted": True,
            "submission_type": "General",
            "reached_out": True,
            "to_who": "Jane Rivera",
            "response_received": False,
            "method": "Linkedin",
            "application_date": "2026-07-01",
            "notes": "Referred by a friend on the platform team.",
        }
    )
    assert app.id
    assert app.created_at and app.updated_at

    reloaded = applications.load_all()
    assert len(reloaded) == 1
    assert reloaded[0].company == "Vandelay"
    assert reloaded[0].to_who == "Jane Rivera"
    assert reloaded[0].submitted is True
    assert reloaded[0].response_received is False
    assert reloaded[0].application_date == "2026-07-01"
    assert reloaded[0].notes == "Referred by a friend on the platform team."
    assert reloaded[0].status == ""  # status defaults to "" when unset


def test_create_with_status(data_dir):
    app = applications.create(
        {
            "company": "Hooli",
            "status": "Applied",
        }
    )
    assert app.status == "Applied"

    reloaded = applications.get(app.id)
    assert reloaded.status == "Applied"


def test_ids_are_unique(data_dir):
    a = applications.create({"company": "Hooli"})
    b = applications.create({"company": "Vandelay"})
    assert a.id != b.id


def test_get_returns_none_for_unknown(data_dir):
    assert applications.get("nope") is None


def test_update_patches_editable_fields_and_bumps_timestamp(data_dir):
    app = applications.create({"company": "Hooli", "submitted": False})
    original_updated = app.updated_at

    updated = applications.update(
        app.id,
        {
            "submitted": True,
            "method": "Email",
            "application_date": "2026-07-05",
            "notes": "Followed up by email.",
        },
    )
    assert updated is not None
    assert updated.submitted is True
    assert updated.method == "Email"
    assert updated.application_date == "2026-07-05"
    assert updated.notes == "Followed up by email."
    assert updated.company == "Hooli"  # untouched field preserved
    assert updated.updated_at >= original_updated

    # Persisted, not just in-memory.
    assert applications.get(app.id).submitted is True
    assert applications.get(app.id).notes == "Followed up by email."


def test_update_status(data_dir):
    app = applications.create({"company": "Hooli", "status": "Applied"})
    assert app.status == "Applied"

    updated = applications.update(app.id, {"status": "Interviewing"})
    assert updated is not None
    assert updated.status == "Interviewing"
    assert updated.company == "Hooli"  # other fields preserved

    # Persisted.
    assert applications.get(app.id).status == "Interviewing"


def test_status_preserved_on_unrelated_update(data_dir):
    app = applications.create({"company": "Hooli", "status": "Waiting"})

    updated = applications.update(
        app.id,
        {
            "submitted": True,
            "notes": "Updated notes",
        },
    )
    assert updated is not None
    assert updated.status == "Waiting"  # status unchanged
    assert updated.submitted is True
    assert updated.notes == "Updated notes"


def test_update_unknown_returns_none(data_dir):
    assert applications.update("nope", {"company": "X"}) is None


def test_general_application_has_no_posting(data_dir):
    app = applications.create({"company": "Portal Co", "submission_type": "General"})
    assert app.posting == ""


def test_atomic_write_leaves_no_tmp(data_dir):
    applications.create({"company": "Hooli"})
    tmp = applications_path().with_suffix(".json.tmp")
    assert not tmp.exists()


def test_save_cv_document_attaches_source_and_filenames(data_dir):
    app = applications.create({"company": "Hooli"})
    saved = applications.save_cv_document(app.id, "<html>edited cv</html>")
    assert saved is not None
    assert saved.cv_document is not None
    assert saved.cv_document.source == "<html>edited cv</html>"
    pdf, docx = cv_filenames(app.id)
    assert saved.cv_document.pdf_filename == pdf
    assert saved.cv_document.docx_filename == docx
    assert saved.cv_document.updated_at

    # Survives a reload.
    assert applications.get(app.id).cv_document.source == "<html>edited cv</html>"


def test_save_cover_letter_document(data_dir):
    app = applications.create({"company": "Hooli"})
    saved = applications.save_cover_letter_document(app.id, "Dear team,")
    assert saved.cover_letter_document.source == "Dear team,"
    pdf, docx = cover_letter_filenames(app.id)
    assert saved.cover_letter_document.pdf_filename == pdf


def test_delete_removes_record_and_owned_files(data_dir):
    app = applications.create({"company": "Hooli"})
    applications.save_cv_document(app.id, "cv")
    # Simulate rendered files existing on the volume.
    pdf, docx = cv_filenames(app.id)
    (data_dir / pdf).write_bytes(b"%PDF-1.4")
    (data_dir / docx).write_bytes(b"docx")

    assert applications.delete(app.id) is True
    assert applications.get(app.id) is None
    assert not (data_dir / pdf).exists()
    assert not (data_dir / docx).exists()


def test_delete_unknown_returns_false(data_dir):
    assert applications.delete("nope") is False


def test_create_for_screening_is_idempotent(data_dir):
    first, created_first = create_for_screening({"company": "Hooli"}, "s1")
    assert created_first is True
    assert first.screening_id == "s1"

    second, created_second = create_for_screening({"company": "Hooli"}, "s1")
    assert created_second is False
    assert second.id == first.id

    # Exactly one persisted row keys on that screening_id.
    matching = [a for a in applications.load_all() if a.screening_id == "s1"]
    assert len(matching) == 1
    assert matching[0].id == first.id


def test_create_for_screening_distinct_ids_create_separate_rows(data_dir):
    a, created_a = create_for_screening({"company": "Hooli"}, "s1")
    b, created_b = create_for_screening({"company": "Vandelay"}, "s2")

    assert created_a is True
    assert created_b is True
    assert a.id != b.id
    assert {app.screening_id for app in applications.load_all()} == {"s1", "s2"}
    assert len(applications.load_all()) == 2


def test_create_defaults_application_date_to_today_when_absent(data_dir):
    app = applications.create({"company": "Hooli"})
    assert app.application_date == date.today().isoformat()


def test_create_preserves_explicitly_supplied_application_date(data_dir):
    app = applications.create({"company": "Hooli", "application_date": "2026-07-01"})
    assert app.application_date == "2026-07-01"


def test_create_for_screening_defaults_application_date_to_today(data_dir):
    app, created = create_for_screening({"company": "Hooli"}, "s1")
    assert created is True
    assert app.application_date == date.today().isoformat()


def test_create_for_screening_empty_id_never_dedupes(data_dir):
    a, created_a = create_for_screening({"company": "Hooli"}, "")
    b, created_b = create_for_screening({"company": "Hooli"}, "")

    assert created_a is True
    assert created_b is True
    assert a.id != b.id
    assert len(applications.load_all()) == 2
