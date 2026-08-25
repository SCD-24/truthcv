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


# ---------------------------------------------------------------------------
# Sign-off
# ---------------------------------------------------------------------------

class TestSignOff:
    """The finished letter closes with the operator's stored name.

    The style prompt forbids the model from writing the candidate's name, so
    the signature is appended deterministically after validation instead.
    """

    def test_sign_off_is_appended(self):
        from coverletter.generate import _with_sign_off

        assert _with_sign_off("Body.", "Glenn Chon") == "Body.\n\nKind regards,\n\nGlenn Chon"

    def test_blank_name_appends_nothing(self):
        """No name is better than an unsigned-looking placeholder."""
        from coverletter.generate import _with_sign_off

        assert _with_sign_off("Body.", "") == "Body."
        assert _with_sign_off("Body.", "   ") == "Body."

    def test_placeholder_name_appends_nothing(self):
        """"[Your Name]" must never ship to an employer as a signature."""
        from coverletter.generate import _with_sign_off

        assert _with_sign_off("Body.", "[Your Name]") == "Body."

    def test_a_name_merely_containing_a_placeholder_appends_nothing(self):
        """The guard must match the guardrail's own test, which scans anywhere.

        Guarding with `fullmatch` let "[Your Name] Smith" through — a literal
        template slot, shipped to an employer, which is exactly what the
        placeholder check exists to stop.
        """
        from coverletter.generate import _with_sign_off

        assert _with_sign_off("Body.", "[Your Name] Smith") == "Body."
        assert _with_sign_off("Body.", "Glenn [Your Name]") == "Body."
        assert _with_sign_off("Body.", "Ada [Company] Lovelace") == "Body."

    def test_a_sentence_length_name_appends_nothing(self):
        """`answers.name` has no validator, and the sign-off lands AFTER the
        guardrail — so an unbounded value would smuggle an unverified claim
        into a guardrailed letter with nothing left to check it."""
        from coverletter.generate import _with_sign_off

        smuggled = "Dr. Glenn Chon, ex-Google Staff Engineer with 15 years at NASA"
        assert _with_sign_off("Body.", smuggled) == "Body."

    def test_a_long_but_genuine_name_still_signs(self):
        """The bound must not refuse real names with post-nominals."""
        from coverletter.generate import _with_sign_off

        name = "Jean-Luc Picard-Fauchelevent OBE PhD"
        assert _with_sign_off("Body.", name).endswith(name)

    def test_whitespace_in_name_is_normalized(self):
        from coverletter.generate import _with_sign_off

        assert _with_sign_off("Body.", "  Glenn \n Chon ").endswith("Glenn Chon")

    def test_sign_off_is_its_own_paragraph_block(self):
        """Consumers split on the blank line: the renderers to make paragraphs,
        the agent to paste into a form. A single newline would collapse."""
        from coverletter.generate import _with_sign_off

        blocks = _with_sign_off("Body.", "Glenn Chon").split("\n\n")
        assert blocks == ["Body.", "Kind regards,", "Glenn Chon"]
