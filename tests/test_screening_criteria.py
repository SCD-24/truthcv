"""screening.criteria: normalization and profile/posting compatibility checks."""

from __future__ import annotations

import pytest

from screening.criteria import (
    REMOTE_ARRANGEMENT_VALUES,
    evaluate,
    language_compatible,
    remote_compatible,
    validate_language_requirement,
    validate_remote_arrangement,
)


class TestValidateRemoteArrangement:
    @pytest.mark.parametrize("value", REMOTE_ARRANGEMENT_VALUES)
    def test_accepts_every_known_value(self, value):
        assert validate_remote_arrangement(value) == value

    @pytest.mark.parametrize(
        "alias", ["onsite", "on-site", "office", "ONSITE", " On-Site ", "OFFICE"]
    )
    def test_on_site_aliases_normalize(self, alias):
        assert validate_remote_arrangement(alias) == "on_site"

    @pytest.mark.parametrize("value", [" Remote ", "REMOTE", "Hybrid", "UNSTATED"])
    def test_case_and_whitespace_insensitive(self, value):
        assert validate_remote_arrangement(value) == value.strip().casefold()

    def test_unknown_value_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown remote arrangement"):
            validate_remote_arrangement("moon-base")

    def test_error_names_allowed_values(self):
        with pytest.raises(ValueError, match="remote, hybrid, on_site, unstated"):
            validate_remote_arrangement("nope")


class TestValidateLanguageRequirement:
    @pytest.mark.parametrize("value", ["", "none", "None", "NONE", "  "])
    def test_no_requirement_normalizes_to_empty(self, value):
        assert validate_language_requirement(value) == ""

    def test_normalizes_case_and_whitespace(self):
        assert validate_language_requirement("  German  ") == "german"

    def test_collapses_internal_whitespace(self):
        assert validate_language_requirement("Swiss   German") == "swiss german"

    def test_non_string_yields_empty(self):
        assert validate_language_requirement(None) == ""


class TestRemoteCompatible:
    @pytest.mark.parametrize("arrangement", ["remote", "unstated", ""])
    def test_remote_profile_accepts(self, arrangement):
        assert remote_compatible("remote", arrangement) is True

    def test_remote_profile_rejects_hybrid(self):
        assert remote_compatible("remote", "hybrid") is False

    def test_remote_profile_rejects_on_site(self):
        assert remote_compatible("remote", "on_site") is False

    @pytest.mark.parametrize("arrangement", ["remote", "hybrid", "unstated", ""])
    def test_hybrid_profile_accepts(self, arrangement):
        assert remote_compatible("hybrid", arrangement) is True

    def test_hybrid_profile_rejects_on_site(self):
        assert remote_compatible("hybrid", "on_site") is False

    @pytest.mark.parametrize("arrangement", REMOTE_ARRANGEMENT_VALUES)
    def test_on_site_profile_accepts_anything(self, arrangement):
        assert remote_compatible("on_site", arrangement) is True

    @pytest.mark.parametrize("profile", [None, ""])
    @pytest.mark.parametrize("arrangement", REMOTE_ARRANGEMENT_VALUES)
    def test_unset_profile_accepts_anything(self, profile, arrangement):
        assert remote_compatible(profile, arrangement) is True

    @pytest.mark.parametrize("arrangement", REMOTE_ARRANGEMENT_VALUES)
    def test_unknown_profile_value_accepts_anything(self, arrangement):
        assert remote_compatible("flexible", arrangement) is True


class TestLanguageCompatible:
    def test_unset_working_language_accepts_anything(self):
        assert language_compatible(None, "german") is True
        assert language_compatible("", "german") is True

    def test_no_requirement_is_always_compatible(self):
        assert language_compatible("german", "") is True

    def test_matching_language_is_compatible(self):
        assert language_compatible("German", "german") is True

    def test_matching_ignores_case_and_whitespace(self):
        assert language_compatible("  GERMAN ", "german") is True

    def test_different_language_is_incompatible(self):
        assert language_compatible("english", "german") is False

    def test_no_fuzzy_matching(self):
        assert language_compatible("german", "deutsch") is False


class TestEvaluate:
    def test_fully_compatible_returns_empty_pair(self):
        assert evaluate("remote", "german", "remote", "german") == ("", "")

    def test_unset_profile_and_no_requirement_is_compatible(self):
        assert evaluate(None, None, "on_site", "") == ("", "")

    def test_remote_mismatch_is_reported(self):
        criterion, reason = evaluate("remote", None, "on_site", "")
        assert criterion == "remote_model"
        assert "remote" in reason
        assert "on_site" in reason

    def test_language_mismatch_is_reported(self):
        criterion, reason = evaluate(None, "german", "remote", "french")
        assert criterion == "working_language"
        assert "german" in reason
        assert "french" in reason

    def test_remote_checked_before_language_when_both_fail(self):
        criterion, _ = evaluate("remote", "german", "on_site", "french")
        assert criterion == "remote_model"
