"""screening.company: normalization and the rules that reject an unusable name."""

from __future__ import annotations

import pytest

from screening.company import normalize_company_name, validate_company_name


class TestNormalizeCompanyName:
    def test_collapses_whitespace(self):
        assert normalize_company_name("Acme   \n  GmbH") == "Acme GmbH"

    def test_strips_edge_separators(self):
        assert normalize_company_name("— Acme GmbH |") == "Acme GmbH"

    def test_keeps_interior_punctuation(self):
        """A separator inside the name is part of it, not an edge to strip."""
        assert normalize_company_name("Smart-Working Solutions") == "Smart-Working Solutions"

    def test_non_string_yields_empty_rather_than_raising(self):
        assert normalize_company_name(None) == ""
        assert normalize_company_name(7) == ""


class TestValidateCompanyName:
    def test_returns_normalized_name(self):
        assert validate_company_name("  Acme   GmbH ") == "Acme GmbH"

    @pytest.mark.parametrize("blank", ["", "   ", "\n\t", "---"])
    def test_blank_is_rejected(self, blank):
        with pytest.raises(ValueError, match="company name is required"):
            validate_company_name(blank)

    @pytest.mark.parametrize(
        "placeholder", ["Unknown", "N/A", "confidential", "TBD", "The Company", "not stated"]
    )
    def test_placeholder_is_rejected(self, placeholder):
        """A placeholder is worse than a blank: it looks like a real answer."""
        with pytest.raises(ValueError, match="placeholder text"):
            validate_company_name(placeholder)

    def test_url_is_rejected(self):
        with pytest.raises(ValueError, match="looks like a URL"):
            validate_company_name("https://jobs.example.com/acme")

    def test_sentence_length_is_rejected(self):
        with pytest.raises(ValueError, match="too long"):
            validate_company_name("A" * 121)

    def test_no_letters_is_rejected(self):
        with pytest.raises(ValueError, match="no letters"):
            validate_company_name("12345")

    def test_punctuated_names_survive(self):
        """Awkwardly punctuated names of the shape the live agent records must not be caught by the rules."""
        for name in [
            "Medico (nordByte / CARESOFT DAN)",
            "Sable (Sable Technologies GmbH)",
            "OTIS Prof. Mueller AG",
            "adventec group (part of z9K)",
            "Vertua (formerly Zayn)",
            "tessa",
        ]:
            assert validate_company_name(name) == name
