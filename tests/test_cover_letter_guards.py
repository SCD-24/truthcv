"""Two guards on the finished letter: labelled facts validate, placeholders don't ship.

Both concern what reaches an employer, and neither was covered before.
"""

from __future__ import annotations

from coverletter.generate import _facts_block_lines, _placeholders, build_letter
from guardrail import validate
from coverletter.generate import _letter_scope
from truth.model import Bullet, Experience, Profile, Truth


def _truth() -> Truth:
    return Truth(
        profile=Profile(name="Glenn Chon", location="Karlsruhe", email="g@example.com"),
        experiences=[
            Experience(
                id="exp-cinemo-1",
                role="Data Engineer",
                company="Cinemo",
                start="2024",
                end="Present",
                source="linkedin-pdf",
                bullets=[
                    Bullet(
                        id="exp-cinemo-1-b1",
                        value="Built Airflow DAGs in Python",
                        source="linkedin-pdf",
                    )
                ],
            )
        ],
        education=[],
        skills=[],
    )


class _Provider:
    """build_letter must not call the model when paragraphs are supplied."""

    def extract_json(self, *a, **k):  # pragma: no cover - must never run
        raise AssertionError("build_letter generated paragraphs when given some")


def _build(paragraphs):
    return build_letter(
        posting="Backend Engineer",
        tone="professional",
        length="short",
        truth=_truth(),
        provider=_Provider(),
        paragraphs=paragraphs,
    )


def test_label_prefixed_claim_is_traceable():
    """The facts block labels each fact and the prompt says quote it verbatim.

    A model that complies emits "Location: Karlsruhe"; the label word appears in
    no truth value, which used to flag `location` and block the whole letter.
    """
    scope = _letter_scope(
        [{"text": "x", "claims": ["Location: Karlsruhe"]}], _truth(), set(), set(), None
    )
    result = validate([scope])
    assert result.ok, f"blocked on {result.unverifiable}"


def test_bare_value_still_traceable():
    scope = _letter_scope(
        [{"text": "x", "claims": ["Karlsruhe"]}], _truth(), set(), set(), None
    )
    assert validate([scope]).ok


def test_invented_fact_still_blocked():
    """Widening the allowed set must not let an unsupported claim through."""
    scope = _letter_scope(
        [{"text": "x", "claims": ["Location: Reykjavik"]}], _truth(), set(), set(), None
    )
    result = validate([scope])
    assert not result.ok
    assert "reykjavik" in result.unverifiable


def test_facts_block_lines_are_labelled():
    lines = _facts_block_lines(_truth(), None)
    assert "Location: Karlsruhe" in lines


def test_placeholder_blocks_the_letter():
    result = _build([{"text": "I want this role.\n\nSincerely,\n[Your Name]", "claims": []}])
    assert result["blocked"] is True
    assert result["text"] == ""
    assert [c.text for c in result["blocked_claims"]] == ["[Your Name]"]


def test_clean_letter_passes():
    result = _build([{"text": "I want this role at Cinemo.", "claims": ["Cinemo"]}])
    assert result["blocked"] is False
    assert result["text"] == "I want this role at Cinemo."


def test_bracket_matching_is_deliberately_broad():
    """Any short bracketed word blocks, including prose like "[sic]".

    Deliberate: the two errors are not symmetric. A false positive blocks a
    letter the operator then sees; a false negative mails "[Your Name]" to an
    employer. Bracketed asides are near-absent from cover letters, so the
    broad rule costs little. Digits are excluded so "[2024]" passes.
    """
    assert _placeholders("shipped in [2024]") == []
    assert _placeholders("noted [sic] there") == ["[sic]"]
    assert _placeholders("Dear [Hiring Manager]") == ["[Hiring Manager]"]


def test_placeholders_are_deduped_in_order():
    assert _placeholders("[Company] then [Your Name] then [Company]") == [
        "[Company]",
        "[Your Name]",
    ]
