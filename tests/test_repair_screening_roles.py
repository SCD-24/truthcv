"""Repair pass over stored screening roles: dry-run writes nothing, --apply
normalizes only what is fixable, an unusable role is reported but never
rewritten, and a second --apply is a no-op. Every test uses the `data_dir`
fixture (tests/conftest.py) so nothing here ever touches the real ./data.
"""

from __future__ import annotations

import screening.store as screening_store
from scripts.repair_screening_roles import main


def _make(data_dir, role, company="Acme", url="https://jobs.example.com/1"):
    """Create a screening record with the given role; returns the Screening."""
    return screening_store.create(
        {"company": company, "role": role, "url": url, "verdict": "rejected"}
    )


def test_dry_run_writes_nothing_and_reports_counts(data_dir, capsys):
    """Dry run (default) must not touch screenings.json and must report the
    right unchanged/normalized/manual-repair counts."""
    _make(data_dir, "Senior Backend Engineer", company="Clean")
    _make(data_dir, "  Senior   Backend\nEngineer  ", company="Mangled")
    _make(data_dir, "", company="Blank")

    path = screening_store.screenings_path()
    before = path.read_bytes()

    main([])

    assert path.read_bytes() == before
    out = capsys.readouterr().out
    assert "unchanged: 1" in out
    assert "normalized: 1" in out
    assert "needs-manual-repair: 1" in out


def test_apply_normalizes_mangled_role_and_leaves_clean_one_alone(data_dir):
    """--apply rewrites only the mangled record's role, through the store."""
    clean = _make(data_dir, "Senior Backend Engineer", company="Clean")
    mangled = _make(data_dir, "  Senior   Backend\nEngineer  ", company="Mangled")

    main(["--apply"])

    by_id = {s.id: s for s in screening_store.load_all()}
    assert by_id[clean.id].role == "Senior Backend Engineer"
    assert by_id[mangled.id].role == "Senior Backend Engineer"


def test_blank_role_is_not_modified_and_is_listed_for_manual_repair(data_dir, capsys):
    """A blank role is reported in the manual-repair list with its screening
    id, and --apply leaves it exactly as stored (never blanked further)."""
    blank = _make(data_dir, "", company="Blank")

    main(["--apply"])

    stored = screening_store.get(blank.id)
    assert stored.role == ""
    out = capsys.readouterr().out
    assert blank.id in out


def test_board_noise_role_is_not_modified_and_is_listed_for_manual_repair(
    data_dir, capsys
):
    """A board-noise placeholder ('Apply now') is reported for manual repair
    and --apply must not rewrite it to anything, including its own casing."""
    noise = _make(data_dir, "Apply now", company="Noisy")

    main(["--apply"])

    stored = screening_store.get(noise.id)
    assert stored.role == "Apply now"
    out = capsys.readouterr().out
    assert noise.id in out


def test_second_apply_reports_zero_normalized(data_dir, capsys):
    """Idempotence: once a fixable record's role equals its normalized form,
    a second --apply run must report 0 normalized."""
    _make(data_dir, "  Senior   Backend\nEngineer  ", company="Mangled")
    _make(data_dir, "", company="Blank")

    main(["--apply"])
    capsys.readouterr()
    main(["--apply"])

    out = capsys.readouterr().out
    assert "normalized: 0" in out


def test_empty_screenings_file_is_handled_without_raising(data_dir):
    """An absent screenings.json (nothing ever created) must not raise."""
    assert screening_store.screenings_path().exists() is False
    main([])
    main(["--apply"])
