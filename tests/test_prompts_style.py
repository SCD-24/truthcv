"""Pin the anti-'AI tell' style properties of the generation prompts.

These prompts instruct the model to avoid em/en dashes and curly quotes in
output. The prompt text must not itself model those characters (a structured
date range is the one deliberate exemption), or the model will happily echo
them. Guards against a future edit reintroducing a banned character.
"""

from truth.model import Bullet, Experience, Skill, Truth
from prompts.tailor import select_system, select_truth_block
from prompts.coverletter import cover_letter_system, cover_letter_facts_block
from prompts.style import (
    CV_STYLE,
    LETTER_STYLE,
    cv_style,
    letter_style,
    cv_anti_slop,
    letter_anti_slop,
)
from prompts.conventions import DEFAULT_CONVENTIONS, DomainVocabulary

EM_DASH = "\u2014"
EN_DASH = "\u2013"
CURLY = "\u2018\u2019\u201c\u201d"  # ' ' " "


def _truth() -> Truth:
    return Truth(
        experiences=[
            Experience(
                id="e1",
                role="Engineer",
                company="Acme",
                start="2020",
                end="2023",
                source="linkedin-pdf",
                bullets=[Bullet(id="b1", value="Built X", source="linkedin-pdf")],
            )
        ],
        skills=[Skill(id="s1", value="Python", source="linkedin-pdf")],
    )


def _assert_no_tells(text: str) -> None:
    assert EM_DASH not in text, "em dash must not appear in prompt prose"
    assert EN_DASH not in text, "en dash must not appear in prompt prose"
    for ch in CURLY:
        assert ch not in text, "curly quotes must not appear in prompt prose"


def test_cv_system_prompt_has_no_ai_tell_characters():
    _assert_no_tells(select_system())


def test_cover_letter_system_prompt_has_no_ai_tell_characters():
    for tone in ("professional", "warm", "concise", "unknown"):
        _assert_no_tells(cover_letter_system(tone, "short"))


def test_cover_letter_facts_block_has_no_ai_tell_characters():
    _assert_no_tells(cover_letter_facts_block(_truth()))


def test_cv_date_range_keeps_exempt_en_dash():
    # The structured date range is the deliberate exemption: its spaced en-dash is
    # a guardrail tokenization mechanism, so it MUST survive.
    assert "2020 " + EN_DASH + " 2023" in select_truth_block(_truth())


def test_cv_system_prompt_has_anti_slop_bans():
    prompt = select_system()
    assert "portability test" in prompt
    assert "Do not rotate synonyms" in prompt
    assert "vague-scale words" in prompt
    assert "dramatic clauses" in prompt


def test_cover_letter_system_prompt_has_anti_slop_bans_for_every_tone():
    for tone in ("professional", "warm", "concise", "unknown"):
        prompt = cover_letter_system(tone, "one page")
        assert "portability test" in prompt
        assert "summary-recap paragraph" in prompt
        assert "Avoid hollow adverbs in the letter" in prompt


def test_cover_letter_system_prompt_ends_with_guardrail_contract():
    for tone in ("professional", "warm", "concise", "unknown"):
        prompt = cover_letter_system(tone, "one page")
        assert prompt.rstrip().endswith(
            "Connective and interpretive sentences carry no claims, that is "
            "where your voice lives, so use them freely."
        )


def test_anti_slop_fragments_have_no_ai_tell_characters():
    _assert_no_tells(cv_anti_slop())
    _assert_no_tells(letter_anti_slop())


def test_default_style_fragments_are_byte_identical_to_constants():
    assert cv_style(DEFAULT_CONVENTIONS) == CV_STYLE
    assert letter_style(DEFAULT_CONVENTIONS) == LETTER_STYLE


def test_cv_system_prompt_plain_action_verbs_are_vocabulary_driven():
    default_prompt = select_system()
    assert "built, led, shipped, owned, cut, raised, fixed" in default_prompt

    custom_prompt = select_system(
        vocabulary=DomainVocabulary(plain_action_verbs="shipped, delivered")
    )
    assert "shipped, delivered" in custom_prompt
    assert "built, led, shipped, owned, cut, raised, fixed" not in custom_prompt
