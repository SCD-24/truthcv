"""Sweep pending screenings with no posting text and no draft: dry-run writes
nothing, --apply rejects only what has nothing to act on, a pending record
with posting text is untouched, a pending blank-text record with a draft is
kept, and a second --apply is a no-op. Every test uses the `data_dir` fixture
(tests/conftest.py) so nothing here ever touches the real ./data.
"""

from __future__ import annotations

import coverletter.store as letter_store
import screening.store as screening_store
from scripts.sweep_unactionable_pending import main


def _make_pending_blank(data_dir, company="Acme", url="https://jobs.example.com/1"):
    """A pending screening with no posting text (mirrors a legacy import)."""
    s = screening_store.create(
        {"company": company, "role": "Dev", "url": url, "verdict": "deferred"}
    )
    assert s.approval == "pending"
    assert s.posting_text == ""
    return s


def test_dry_run_writes_nothing_and_reports_counts(data_dir, capsys):
    _make_pending_blank(data_dir, company="Swept")

    path = screening_store.screenings_path()
    before = path.read_bytes()

    main([])

    assert path.read_bytes() == before
    out = capsys.readouterr().out
    assert "dry run" in out
    assert "swept (rejected" in out
    assert "1" in out.splitlines()[1]


def test_apply_rejects_only_empty_text_draftless_pending_records(data_dir):
    swept = _make_pending_blank(data_dir, company="Swept")

    main(["--apply"])

    stored = screening_store.get(swept.id)
    assert stored.approval == "rejected"


def test_pending_record_with_posting_text_is_untouched(data_dir):
    s = screening_store.create(
        {
            "company": "HasText",
            "role": "Dev",
            "url": "https://jobs.example.com/2",
            "verdict": "deferred",
            "posting_text": "A real posting body describing the role in detail.",
        }
    )
    assert s.approval == "pending"

    main(["--apply"])

    stored = screening_store.get(s.id)
    assert stored.approval == "pending"


def test_pending_blank_text_record_with_draft_is_kept(data_dir):
    kept = _make_pending_blank(data_dir, company="Kept")
    letter_store.save(kept.id, letter_store.CoverLetterDraft(text="Dear hiring manager, ..."))

    main(["--apply"])

    stored = screening_store.get(kept.id)
    assert stored.approval == "pending"


def test_non_pending_record_is_untouched(data_dir):
    s = screening_store.create(
        {"company": "Rejected", "role": "Dev", "url": "https://jobs.example.com/3", "verdict": "rejected"}
    )
    assert s.approval == ""

    main(["--apply"])

    stored = screening_store.get(s.id)
    assert stored.approval == ""


def test_second_apply_is_idempotent(data_dir):
    swept = _make_pending_blank(data_dir, company="Swept")

    main(["--apply"])
    first = screening_store.get(swept.id).approval

    main(["--apply"])
    second = screening_store.get(swept.id).approval

    assert first == second == "rejected"


def test_empty_screenings_file_is_handled_without_raising(data_dir):
    assert screening_store.screenings_path().exists() is False
    main([])
    main(["--apply"])
