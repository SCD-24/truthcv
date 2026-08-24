"""Per-screening cover letter drafts.

One file per screening rather than a field on the screening record: the letter
is rewritten repeatedly and is orders of magnitude larger than the record, and
screenings.json is loaded in full on every screening read.
"""

from __future__ import annotations

import coverletter.store as letters


def _draft(text="Dear hiring team,", source="generated"):
    return letters.CoverLetterDraft(
        text=text, paragraphs=[{"text": text, "claims": []}], source=source
    )


def test_load_missing_returns_none(data_dir):
    assert letters.load("nope") is None


def test_save_and_load_round_trip(data_dir):
    saved = letters.save("s1", _draft())
    assert saved.updated_at
    loaded = letters.load("s1")
    assert loaded.text == "Dear hiring team,"
    assert loaded.source == "generated"
    assert loaded.paragraphs == [{"text": "Dear hiring team,", "claims": []}]


def test_operator_save_overwrites_a_generated_draft(data_dir):
    letters.save("s1", _draft())
    letters.save("s1", _draft(text="My own words.", source="operator"))
    loaded = letters.load("s1")
    assert loaded.text == "My own words."
    assert loaded.source == "operator"


def test_corrupt_file_loads_as_none(data_dir):
    letters.save("s1", _draft())
    letters.draft_path("s1").write_text("{ not json", encoding="utf-8")
    assert letters.load("s1") is None


def test_unknown_source_falls_back_to_generated(data_dir):
    """A wrong-typed field must not make text look operator-authored when it
    is not: `source` is the audit trail for what the guardrail vouched for."""
    letters.save("s1", _draft())
    letters.draft_path("s1").write_text('{"text": "x", "source": 7}', encoding="utf-8")
    assert letters.load("s1").source == "generated"


def test_delete(data_dir):
    letters.save("s1", _draft())
    assert letters.delete("s1") is True
    assert letters.load("s1") is None
    assert letters.delete("s1") is False


def test_screening_id_cannot_escape_the_letters_dir(data_dir):
    """Ids come from the store, but the id also arrives in a URL path."""
    import pytest

    with pytest.raises(ValueError):
        letters.draft_path("../../etc/passwd")
