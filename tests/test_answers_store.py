"""Answers store: blank defaults, persistence, canonical CV registration,
seeding from a YAML file, and isolation from truth.yaml."""

from __future__ import annotations

import dataclasses

import pytest

from truth.answers import (
    Answers,
    CanonicalCvAsset,
    _applicable_fields,
    answers_path,
    canonical_cv,
    load,
    register_canonical_cv,
    save,
    seed_answers,
)


def test_absent_file_loads_blank_defaults(data_dir):
    """A missing answers.yaml loads a fully blank (not None) Answers record."""
    assert not answers_path().exists()
    answers = load()
    assert answers == Answers()
    # every string field starts blank; only canonical_cv_asset_id is unset
    assert answers.phone == ""
    assert answers.name == ""
    assert answers.canonical_cv_asset_id is None


def test_fresh_answers_has_no_personal_defaults():
    """Regression guard: every string field on a fresh Answers() is blank.

    Derives the field list from dataclasses.fields rather than hardcoding
    names, so a newly added field is covered automatically and can never
    ship a populated personal default again.
    """
    answers = Answers()
    for field in dataclasses.fields(Answers):
        if field.name == "canonical_cv_asset_id":
            assert getattr(answers, field.name) is None
        else:
            assert getattr(answers, field.name) == ""


def test_save_load_round_trip(data_dir):
    """Saved answers reload byte-for-byte identical."""
    original = Answers()
    original.phone = "+1 555 0100"
    original.years_of_experience = "12"
    save(original)
    assert answers_path().exists()
    reloaded = load()
    assert reloaded == original


def test_save_writes_atomically_leaves_no_tmp(data_dir):
    """save() leaves no leftover .yaml.tmp file behind."""
    save(Answers())
    assert answers_path().exists()
    tmp = answers_path().with_suffix(".yaml.tmp")
    assert not tmp.exists()


def test_saving_answers_does_not_touch_truth_yaml(data_dir):
    """Saving answers never creates truth.yaml."""
    from truth.store import truth_path

    assert not truth_path().exists()
    save(Answers())
    assert not truth_path().exists()


def test_saving_answers_does_not_modify_existing_truth_yaml(data_dir):
    """Saving answers leaves an existing truth.yaml byte-for-byte unchanged."""
    from truth.store import truth_path

    truth_path().write_text("experiences: []\n", encoding="utf-8")
    before = truth_path().read_bytes()
    save(Answers())
    after = truth_path().read_bytes()
    assert after == before


def test_register_canonical_cv_and_lookup_by_id(data_dir, tmp_path_factory):
    """A registered CV is copied onto the data volume and resolvable by id."""
    # Source lives in a directory entirely outside the data volume, so the
    # test actually exercises a copy onto data_dir rather than a same-place
    # no-op.
    source_dir = tmp_path_factory.mktemp("source")
    source = source_dir / "source_cv.pdf"
    payload = b"%PDF-1.4 fake canonical cv bytes for round trip test\n"
    source.write_bytes(payload)
    assert data_dir not in source.parents

    result = register_canonical_cv(source)
    assert result.canonical_cv_asset_id == "canonical_cv.pdf"

    # persisted, so a fresh load reflects it too
    assert load().canonical_cv_asset_id == "canonical_cv.pdf"

    asset = canonical_cv()
    assert asset is not None
    assert asset == CanonicalCvAsset(
        asset_id="canonical_cv.pdf", path=data_dir / "canonical_cv.pdf"
    )
    # destination lives under the data volume, distinct from the source
    assert asset.path.parent == data_dir
    # byte-identical copy on the data volume
    assert asset.path.read_bytes() == payload
    # atomic rename leaves no leftover temp file behind
    assert not (data_dir / "canonical_cv.pdf.tmp").exists()


def test_canonical_cv_none_when_unregistered(data_dir):
    """canonical_cv() is None when nothing has been registered."""
    assert canonical_cv() is None


def test_partial_data_only_overrides_given_fields(data_dir):
    """A partial answers.yaml only overrides the keys it contains."""
    raw_yaml = "phone: '+44 20 7946 0958'\nyears_of_experience: '3'\n"
    answers_path().write_text(raw_yaml, encoding="utf-8")

    answers = load()
    defaults = Answers()
    assert answers.phone == "+44 20 7946 0958"
    assert answers.years_of_experience == "3"
    # everything else still falls back to the blank defaults
    assert answers.name == defaults.name
    assert answers.salary_expectation == defaults.salary_expectation
    assert answers.canonical_cv_asset_id is None


def test_seed_answers_applies_given_keys(data_dir, tmp_path_factory):
    """seed_answers applies every field present in the source file."""
    seed_dir = tmp_path_factory.mktemp("seed")
    seed_file = seed_dir / "answers.local.yaml"
    seed_file.write_text(
        "phone: '+49 30 0000 0000'\nname: Ada Example\n", encoding="utf-8"
    )

    result = seed_answers(seed_file)
    assert result.phone == "+49 30 0000 0000"
    assert result.name == "Ada Example"
    assert load().phone == "+49 30 0000 0000"


def test_seed_answers_merges_keeping_absent_keys(data_dir, tmp_path_factory):
    """A key absent from the seed file keeps its previously stored value."""
    save(Answers(phone="+49 30 0000 0000", email="ada@example.com"))
    seed_dir = tmp_path_factory.mktemp("seed")
    seed_file = seed_dir / "answers.local.yaml"
    seed_file.write_text("name: Ada Example\n", encoding="utf-8")

    result = seed_answers(seed_file)
    assert result.name == "Ada Example"
    # untouched by the seed file, so the previously stored values survive
    assert result.phone == "+49 30 0000 0000"
    assert result.email == "ada@example.com"


def test_seed_answers_never_overwrites_canonical_cv_asset_id(data_dir, tmp_path_factory):
    """An already-registered canonical CV survives seeding untouched."""
    save(Answers(canonical_cv_asset_id="canonical_cv.pdf"))
    seed_dir = tmp_path_factory.mktemp("seed")
    seed_file = seed_dir / "answers.local.yaml"
    seed_file.write_text("canonical_cv_asset_id: intruder.pdf\n", encoding="utf-8")

    result = seed_answers(seed_file)
    assert result.canonical_cv_asset_id == "canonical_cv.pdf"


def test_seed_answers_omitted_value_leaves_stored_value_untouched(data_dir, tmp_path_factory):
    """A key present with no value (parses to None) is skipped, not stored as "None".

    Pre-fix, `setattr(answers, name, str(value))` would stringify the None
    parsed from `gpa:` into the literal string "None" and store that.
    """
    save(Answers(gpa="3.9"))
    seed_dir = tmp_path_factory.mktemp("seed")
    seed_file = seed_dir / "answers.local.yaml"
    seed_file.write_text("gpa:\n", encoding="utf-8")

    result = seed_answers(seed_file)
    assert result.gpa == "3.9"
    assert result.gpa != "None"


def test_seed_answers_blank_or_whitespace_value_leaves_stored_value_untouched(
    data_dir, tmp_path_factory
):
    """Empty-string and whitespace-only values are skipped, keeping the stored value.

    Pre-fix, both would overwrite the stored values with "" and " ".
    """
    save(Answers(phone="+49 30 0000 0000", email="ada@example.com"))
    seed_dir = tmp_path_factory.mktemp("seed")
    seed_file = seed_dir / "answers.local.yaml"
    seed_file.write_text("phone: ''\nemail: '   '\n", encoding="utf-8")

    result = seed_answers(seed_file)
    assert result.phone == "+49 30 0000 0000"
    assert result.email == "ada@example.com"


def test_seed_answers_fully_blank_template_changes_nothing(data_dir, tmp_path_factory):
    """Seeding the shipped example template (all keys blank) is a no-op.

    Pre-fix, this would overwrite every stored field with "" and still report
    a nonzero applied count, silently wiping stored personal data.
    """
    stored = Answers(
        phone="+49 30 0000 0000",
        name="Ada Example",
        email="ada@example.com",
        gpa="3.9",
    )
    save(stored)
    seed_dir = tmp_path_factory.mktemp("seed")
    seed_file = seed_dir / "answers.local.yaml"
    field_names = {f.name for f in dataclasses.fields(Answers)} - {"canonical_cv_asset_id"}
    seed_file.write_text(
        "\n".join(f'{name}: ""' for name in sorted(field_names)) + "\n",
        encoding="utf-8",
    )

    before = load()
    result = seed_answers(seed_file)
    assert result == before
    assert load() == before

    raw = {name: "" for name in field_names}
    assert len(_applicable_fields(raw)) == 0


def test_seed_answers_rejects_non_mapping_yaml(data_dir, tmp_path_factory):
    """A seed file that doesn't parse to a mapping raises ValueError."""
    seed_dir = tmp_path_factory.mktemp("seed")
    seed_file = seed_dir / "answers.local.yaml"
    seed_file.write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(ValueError):
        seed_answers(seed_file)


def test_seed_answers_missing_file_raises(data_dir, tmp_path_factory):
    """A seed path that isn't a file raises FileNotFoundError."""
    missing = tmp_path_factory.mktemp("seed") / "does_not_exist.yaml"

    with pytest.raises(FileNotFoundError):
        seed_answers(missing)
