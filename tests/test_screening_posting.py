"""screening.posting: normalization and the rules that reject unusable posting text."""

from __future__ import annotations

import pytest

from screening.posting import (
    MIN_POSTING_TEXT_CHARS,
    normalize_posting_text,
    validate_posting_text,
)


def _long_posting(body: str = "") -> str:
    """Build a realistic posting body comfortably over the char floor."""
    filler = (
        "We are looking for a Senior Backend Engineer to join our platform "
        "team. You will design, build and operate services that power our "
        "product, working closely with product managers and designers. "
        "Requirements: 5+ years of experience with distributed systems, "
        "strong Python or Go skills, and a track record of shipping "
        "reliable software. We offer a competitive salary, remote-friendly "
        "culture, and a generous learning budget. "
    )
    text = filler + body
    while len(text) < MIN_POSTING_TEXT_CHARS + 50:
        text += filler
    return text


class TestNormalizePostingText:
    def test_collapses_whitespace(self):
        assert normalize_posting_text("We are   hiring\n\na Backend Engineer") == (
            "We are hiring a Backend Engineer"
        )

    def test_strips_edges(self):
        assert normalize_posting_text("  Backend Engineer role  ") == "Backend Engineer role"

    def test_non_string_yields_empty_rather_than_raising(self):
        assert normalize_posting_text(None) == ""
        assert normalize_posting_text(7) == ""


class TestValidatePostingText:
    def test_returns_normalized_text_for_real_posting(self):
        posting = _long_posting()
        assert validate_posting_text(posting) == normalize_posting_text(posting)

    @pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
    def test_blank_is_rejected(self, blank):
        with pytest.raises(ValueError, match="Posting text is required"):
            validate_posting_text(blank)

    def test_just_under_floor_is_rejected(self):
        text = "A" * (MIN_POSTING_TEXT_CHARS - 1)
        with pytest.raises(ValueError, match="too short"):
            validate_posting_text(text)

    def test_just_over_floor_is_accepted(self):
        text = "Engineering role requiring strong skills. " * 1
        text = text + "x" * (MIN_POSTING_TEXT_CHARS - len(text) + 1)
        assert len(normalize_posting_text(text)) >= MIN_POSTING_TEXT_CHARS
        assert validate_posting_text(text) == normalize_posting_text(text)

    @pytest.mark.parametrize(
        "phrase",
        [
            "sign in to view",
            "log in to continue",
            "enable javascript",
            "we use cookies",
            "accept cookies",
            "page not found",
            "404",
            "no longer available",
            "no longer accepting applications",
            "position has been filled",
            "access denied",
            "verify you are human",
            "checking your browser",
        ],
    )
    def test_junk_phrase_is_rejected(self, phrase):
        # Padded well past MIN_POSTING_TEXT_CHARS so the rejection is about the
        # junk phrase, not the length floor, while staying under the junk-phrase
        # length ceiling so the match still fires.
        padding = "Please note this notice applies to this page. " * 5
        text = f"{padding}{phrase} {padding}"
        assert MIN_POSTING_TEXT_CHARS <= len(normalize_posting_text(text)) < 1200
        with pytest.raises(ValueError, match="wall/error page"):
            validate_posting_text(text)

    def test_long_posting_mentioning_cookies_is_accepted(self):
        """A genuine long posting that merely mentions cookies must pass."""
        posting = _long_posting(
            "Our office kitchen is always stocked with snacks and cookies for the team. "
            * 15
        )
        assert len(normalize_posting_text(posting)) >= 1200
        assert validate_posting_text(posting) == normalize_posting_text(posting)
