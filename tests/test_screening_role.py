"""Guard tests for screening/role.py: a screening is only actionable if the
operator knows which role it is for, so the title check must collapse noisy
whitespace, strip edge separators without mangling internal punctuation, and
reject placeholder/URL/empty junk — each rejection distinguishable, with the
empty case given its own message (mirroring screening/url.py).
"""

from __future__ import annotations

import pytest

from screening.role import normalize_role_title, validate_role_title


def test_normalize_collapses_whitespace_runs_to_single_spaces():
    """Newlines, tabs, and multiple spaces collapse to a single space."""
    assert normalize_role_title("Senior\n\tData   Engineer") == "Senior Data Engineer"


def test_normalize_strips_surrounding_whitespace():
    """Leading and trailing whitespace is removed entirely."""
    assert normalize_role_title("   Product Manager   ") == "Product Manager"


def test_normalize_strips_surrounding_separator_punctuation():
    """Separator punctuation at the ends is stripped, inner text untouched."""
    assert normalize_role_title("- Senior Engineer -") == "Senior Engineer"
    assert normalize_role_title("| Data Scientist |") == "Data Scientist"
    assert normalize_role_title(": Analyst ;") == "Analyst"


def test_normalize_is_idempotent():
    """Normalizing an already-normalized value changes nothing."""
    for sample in ["- Senior Engineer -", "  Full-Stack  Dev  ", "Backend / Platform Engineer"]:
        once = normalize_role_title(sample)
        assert normalize_role_title(once) == once


def test_normalize_returns_empty_string_for_non_str_input():
    """A non-str input yields "" rather than raising."""
    assert normalize_role_title(None) == ""
    assert normalize_role_title(42) == ""


def test_validate_returns_normalized_good_title():
    """A clean title round-trips through validation normalized."""
    assert validate_role_title("  Senior   Engineer  ") == "Senior Engineer"


def test_validate_keeps_internal_hyphen():
    """An internal hyphen is not an edge separator, so it must survive."""
    assert validate_role_title("Full-Stack Engineer") == "Full-Stack Engineer"


def test_validate_keeps_internal_slash():
    """An internal slash is legitimate title punctuation and must survive."""
    assert validate_role_title("Backend / Platform Engineer") == "Backend / Platform Engineer"


def test_validate_rejects_empty_string():
    """An empty title is unusable and must raise."""
    with pytest.raises(ValueError):
        validate_role_title("")


def test_validate_rejects_whitespace_only():
    """A whitespace-only title normalizes to "" and must raise."""
    with pytest.raises(ValueError):
        validate_role_title("   ")


def test_validate_rejects_board_noise_apply_now():
    """A common board placeholder is not a title and must raise."""
    with pytest.raises(ValueError):
        validate_role_title("Apply now")


def test_validate_rejects_board_noise_case_insensitively():
    """Board noise matches regardless of case or surrounding whitespace."""
    with pytest.raises(ValueError):
        validate_role_title("REMOTE")
    with pytest.raises(ValueError):
        validate_role_title(" n/a ")


def test_validate_rejects_url_value():
    """A pasted URL is not a title and must raise."""
    with pytest.raises(ValueError):
        validate_role_title("https://example.com/jobs/1")


def test_validate_rejects_digits_and_punctuation_only():
    """A value with no alphabetic character is not a title and must raise."""
    with pytest.raises(ValueError):
        validate_role_title("12345-67")


def test_validate_rejects_over_length_title():
    """A title longer than 120 chars after normalization must raise."""
    with pytest.raises(ValueError):
        validate_role_title("x" * 200)


def test_empty_and_malformed_messages_differ():
    """The empty case has its own message, distinct from a malformed one —
    mirroring screening/url.py giving the empty input a dedicated message."""
    with pytest.raises(ValueError) as empty_excinfo:
        validate_role_title("")
    with pytest.raises(ValueError) as url_excinfo:
        validate_role_title("https://example.com/jobs/1")
    assert str(empty_excinfo.value) != str(url_excinfo.value)
