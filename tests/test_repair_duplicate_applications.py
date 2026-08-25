"""Merge duplicate Application rows: URL-suffix/tracking-param clusters and
shared-screening_id clusters fold into their earliest-created canonical row,
losing no notes or evidence; a dry run writes nothing; a second --apply is a
no-op; a duplicate that owns a rendered document is held back as manual-repair
rather than deleted; and genuinely unrelated rows are never touched. Every test
uses the `data_dir` fixture (tests/conftest.py) so nothing here ever touches the
real ./data, and `capsys` captures the printed report where its text is checked.
"""

from __future__ import annotations

import applications.store as applications_store
from scripts.repair_duplicate_applications import main


def _create_at(monkeypatch, ts, fields):
    """Create an application with a controlled ``created_at``.

    ``store.create`` auto-stamps ``created_at`` from ``store._now()`` and does
    not accept it as an editable field, so we pin ``_now`` to ``ts`` for this
    one call to make the earliest-created (canonical) row deterministic.
    """
    monkeypatch.setattr("applications.store._now", lambda: ts)
    return applications_store.create(fields)


def test_url_suffix_and_tracking_param_group_folds_to_first_created(
    data_dir, monkeypatch
):
    """Four rows for one posting whose URLs differ only by an apply-ish trailing
    segment and/or tracking query params merge into the single earliest row."""
    base = "https://x.example.com/j/4d090169"
    first = _create_at(
        monkeypatch,
        "2026-01-01T00:00:01+00:00",
        {"company": "Initech", "application_url": base + "/", "submitted": True},
    )
    _create_at(
        monkeypatch,
        "2026-01-01T00:00:02+00:00",
        {
            "company": "Initech",
            "application_url": base + "/application",
            "submitted": True,
        },
    )
    _create_at(
        monkeypatch,
        "2026-01-01T00:00:03+00:00",
        {
            "company": "Initech",
            "application_url": base + "/application?utm_source=x",
            "submitted": True,
        },
    )
    _create_at(
        monkeypatch,
        "2026-01-01T00:00:04+00:00",
        {"company": "Initech", "application_url": base, "submitted": True},
    )

    main(["--apply"])

    rows = applications_store.load_all()
    assert len(rows) == 1
    assert rows[0].id == first.id
    assert rows[0].company == "Initech"


def test_notes_union_and_evidence_richness(data_dir, monkeypatch):
    """The canonical row keeps every distinct note as its own paragraph and
    gathers the one confirmation and the one fields_submitted from the group."""
    base = "https://x.example.com/j/notes"
    canonical = _create_at(
        monkeypatch,
        "2026-02-01T00:00:01+00:00",
        {
            "company": "Initech",
            "application_url": base,
            "submitted": True,
            "notes": "First attempt via the careers portal.",
        },
    )
    with_conf = _create_at(
        monkeypatch,
        "2026-02-01T00:00:02+00:00",
        {
            "company": "Initech",
            "application_url": base + "/apply",
            "submitted": True,
            "notes": "Retry that carried the confirmation email.",
        },
    )
    with_fields = _create_at(
        monkeypatch,
        "2026-02-01T00:00:03+00:00",
        {
            "company": "Initech",
            "application_url": base + "/application",
            "submitted": True,
            "notes": "Retry that captured the as-submitted fields.",
        },
    )
    applications_store.save_confirmation(
        with_conf.id,
        {"text": "Confirmed via email", "confirmed_at": "2026-02-01", "evidence": "id 7"},
    )
    applications_store.save_fields_submitted(
        with_fields.id,
        [{"label": "Full name", "value": "Ada Lovelace", "source": "profile"}],
    )

    main(["--apply"])

    rows = applications_store.load_all()
    assert len(rows) == 1
    merged = rows[0]
    assert merged.id == canonical.id

    paragraphs = merged.notes.split("\n\n")
    assert paragraphs == [
        "First attempt via the careers portal.",
        "Retry that carried the confirmation email.",
        "Retry that captured the as-submitted fields.",
    ]

    assert merged.confirmation.text == "Confirmed via email"
    assert len(merged.fields_submitted) == 1
    assert merged.fields_submitted[0].value == "Ada Lovelace"


def test_shared_screening_id_groups_despite_different_urls(data_dir, monkeypatch):
    """Two rows sharing a non-empty screening_id merge even though their URLs
    differ and would never bucket together by URL."""
    _create_at(
        monkeypatch,
        "2026-03-01T00:00:01+00:00",
        {
            "company": "Initech",
            "application_url": "https://a.example.com/one",
            "screening_id": "scr-123",
        },
    )
    _create_at(
        monkeypatch,
        "2026-03-01T00:00:02+00:00",
        {
            "company": "Initech",
            "application_url": "https://b.example.com/two",
            "screening_id": "scr-123",
        },
    )

    main(["--apply"])

    rows = applications_store.load_all()
    assert len(rows) == 1
    assert rows[0].screening_id == "scr-123"


def test_dry_run_writes_nothing(data_dir, monkeypatch, capsys):
    """The default (no --apply) must not touch applications.json, yet still
    report the duplicate cluster as a mergeable group."""
    base = "https://x.example.com/j/dry"
    _create_at(
        monkeypatch,
        "2026-04-01T00:00:01+00:00",
        {"company": "Initech", "application_url": base, "submitted": True},
    )
    _create_at(
        monkeypatch,
        "2026-04-01T00:00:02+00:00",
        {"company": "Initech", "application_url": base + "/apply", "submitted": True},
    )

    path = applications_store.applications_path()
    before = path.read_bytes()

    main([])

    assert path.read_bytes() == before
    assert len(applications_store.load_all()) == 2
    out = capsys.readouterr().out
    assert "dry run (nothing written)" in out
    assert "merged: 1 group(s), 1 duplicate row(s)" in out


def test_second_apply_is_a_no_op(data_dir, monkeypatch, capsys):
    """After a first --apply merges a cluster, a second --apply finds only a
    singleton bucket and merges nothing."""
    base = "https://x.example.com/j/again"
    _create_at(
        monkeypatch,
        "2026-05-01T00:00:01+00:00",
        {"company": "Initech", "application_url": base, "submitted": True},
    )
    _create_at(
        monkeypatch,
        "2026-05-01T00:00:02+00:00",
        {"company": "Initech", "application_url": base + "/apply", "submitted": True},
    )

    main(["--apply"])
    after_first = applications_store.load_all()
    assert len(after_first) == 1
    capsys.readouterr()

    main(["--apply"])

    after_second = applications_store.load_all()
    assert len(after_second) == len(after_first)
    out = capsys.readouterr().out
    assert "merged: 0 group(s), 0 duplicate row(s)" in out


def test_duplicate_owning_a_document_is_held_back_as_manual_repair(
    data_dir, monkeypatch, capsys
):
    """A non-canonical duplicate that owns a cv_document is never deleted
    (deleting it would unlink its rendered files) — it is reported instead."""
    _create_at(
        monkeypatch,
        "2026-06-01T00:00:01+00:00",
        {
            "company": "Initech",
            "application_url": "https://c.example.com/one",
            "screening_id": "scr-doc",
        },
    )
    later = _create_at(
        monkeypatch,
        "2026-06-01T00:00:02+00:00",
        {
            "company": "Initech",
            "application_url": "https://c.example.com/two",
            "screening_id": "scr-doc",
        },
    )
    applications_store.save_cv_document(later.id, "<html>rendered cv</html>")

    main(["--apply"])

    ids = {a.id for a in applications_store.load_all()}
    assert later.id in ids
    out = capsys.readouterr().out
    assert later.id in out
    assert "manual-repair" in out


def test_unrelated_applications_are_untouched(data_dir, monkeypatch):
    """Two rows for genuinely different companies/URLs with no shared
    screening_id are both left exactly in place by --apply."""
    a = _create_at(
        monkeypatch,
        "2026-07-01T00:00:01+00:00",
        {"company": "Acme", "application_url": "https://acme.example.com/x", "submitted": True},
    )
    b = _create_at(
        monkeypatch,
        "2026-07-01T00:00:02+00:00",
        {"company": "Globex", "application_url": "https://globex.example.com/y", "submitted": True},
    )

    main(["--apply"])

    rows = applications_store.load_all()
    assert len(rows) == 2
    by_id = {r.id: r for r in rows}
    assert by_id[a.id].company == "Acme"
    assert by_id[b.id].company == "Globex"
