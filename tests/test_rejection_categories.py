import pytest

from screening.rejection_categories import (
    REJECTION_CATEGORIES,
    normalize_failing_criterion as norm,
)


@pytest.mark.parametrize("key", REJECTION_CATEGORIES)
def test_canonical_key_unchanged(key):
    assert norm(key) == key


def test_idempotent_over_sample():
    for x in ["1. Fully remote", "Employment country: Germany", "zzz", "", None,
              "Salary floor", "EOR not allowed", "Cooldown active"]:
        assert norm(norm(x)) == norm(x)


@pytest.mark.parametrize("raw,expected", [
    ("Chief Financial Officer role mismatch", "role_fit"),
    ("contract officer", "rejected_role_types"),
    ("office attendance required", "remote_model"),
])
def test_office_whole_word(raw, expected):
    assert norm(raw) == expected


def test_blank():
    assert norm("") == ""
    assert norm("   ") == ""
    assert norm(None) == ""


@pytest.mark.parametrize("raw,expected", [
    ("Employment country: Germany", "employment_country"),
    ("Remote model", "remote_model"),
    ("1. Fully remote", "remote_model"),
    ("entity", "role_fit"),
    ("qwertyuiop", "other"),
    ("corporate", "other"),
    ("theory of people", "other"),
    ("EOR required", "eor_allowed"),
    ("day rate too low", "salary_floor"),
])
def test_examples(raw, expected):
    assert norm(raw) == expected
