"""Fragment/preset library tests and legacy-equivalence checks.

The equivalence tests lock in that the fragment-based assembler produces the
same sentence content (though not necessarily the same order/slot placement)
as the plain-literal cover letter prompts this project has always produced.
The LEGACY_* constants below are that pre-refactor text, reconstructed from
the exact literals ``prompts/coverletter.py`` and ``prompts/style.py`` used to
hold before they were split into swappable fragments (see the "Text bodies"
comment in ``prompts/fragments.py``), for tone='professional'/'warm'/'concise'
and length='standard' with ``DEFAULT_CONVENTIONS``.

This is a pure data/logic layer: no LLM calls, no mocks, and (via the
autouse ``data_dir`` fixture from ``tests/conftest.py``) no shared state
between tests or with the real ``./data`` directory.
"""

from __future__ import annotations

import json

import pytest

from prompts.assemble import GUARDRAIL_CONTRACT, assemble_system_prompt
from prompts.coverletter import cover_letter_system_for_preset
from prompts.conventions import CvConventions
from prompts.fragments import (
    DEFAULT_CONVENTIONS,
    Fragment,
    Preset,
    SEEDED_FRAGMENTS,
    SEEDED_PRESETS,
    SLOTS,
    seeded_fragments,
)
from prompts.library import (
    PRESETS_FILE,
    default_preset,
    delete_fragment,
    delete_preset,
    get_fragment,
    get_preset,
    list_fragments,
    list_presets,
    set_default_preset,
    upsert_fragment,
    upsert_preset,
)
from storage.paths import data_dir


_FRAMING_STANDARD = (
    "You are writing a compelling, standard-length cover letter that "
    "makes a hiring manager want to meet this candidate. Write a genuine, "
    "engaging letter with a clear throughline about why this candidate "
    "fits this specific role, not a dry recitation of facts."
)

_VOICE_PROFESSIONAL = (
    " Voice: confident and polished, measured, businesslike, and "
    "self-assured without stiffness, letting concrete results speak."
)

_VOICE_WARM = (
    " Voice: warm and personable, genuinely engaged and human, writing "
    "about why this role and organization fit the candidate."
)

_VOICE_CONCISE = (
    " Voice: tight and direct. Every sentence earns its place, short and "
    "specific with no filler, while still reading as a real person, not a "
    "list."
)

_STRUCTURE = (
    " Keep it to 3 to 5 short paragraphs, under one page. Structure: an "
    "opening paragraph that names the role, gives a specific concrete hook "
    "tied to the company or posting, and surfaces the strongest "
    "qualification; middle paragraph(s) that connect past accomplishments "
    "to the employer's likely needs, reference specific projects or "
    "outcomes, and show understanding of the company's goals or industry; "
    "and a closing paragraph that briefly reaffirms fit, states the "
    "ability to contribute, thanks the reader, and ends professionally."
)

_OPENER = (
    " Open with a paragraph that names the role, gives a specific concrete "
    "hook tied to the company or posting, and surfaces the strongest "
    "qualification."
)

_RULES_CAREER_SERVICES = (
    " You are a professional career writer trained to elite university "
    "career-services standards. Produce a tailored, compelling, concise "
    "letter that is personalized to the target company and role, shows "
    "real understanding of the organization, and connects the candidate's "
    "background to the employer's needs. Highlight relevant accomplishments "
    "and transferable skills. Sound confident, articulate, and "
    "professional; avoid generic phrasing and empty enthusiasm. "
    "Principles: clear, direct prose in active voice; prioritize evidence "
    "and examples over claims; show impact through measurable outcomes "
    "when the facts support them; do not repeat the resume verbatim, "
    "reframe achievements toward the employer's needs; keep the tone "
    "natural, not robotic; and go easy on the word 'I', focusing on value "
    "to the employer rather than the candidate's wishes. Hard style "
    "constraints: Do NOT use em dashes or en dashes. Use commas, "
    "parentheses, or semicolons, or split into two sentences. Use "
    "straight quotes (' and \"), never curly quotes. Do not open with "
    "'I am thrilled', 'excited', 'delighted', 'writing to express my "
    "interest', 'I hope this letter finds you well', or 'As a [adjective] "
    "professional with X years'; open with a specific concrete hook tied "
    "to the posting or company. Do not use these words: leverage, delve, "
    "foster, unlock, harness, navigate, spearhead, orchestrate, robust, "
    "comprehensive, seamless, vibrant, intricate, transformative, synergy, "
    "paradigm, tapestry, ecosystem (as metaphor), holistic, innovative, "
    "passionate, dynamic. Avoid contrastive cliches such as 'not just X, "
    "but Y' or 'it's not merely A, it's B'. Avoid stock closers like 'I "
    "look forward to the opportunity to discuss how my skills can "
    "contribute to your team's success'; close briefly and directly. "
    "Prefer short, varied sentences; avoid rule-of-three lists when one "
    "or two items say it better. Prefer concrete numbers and outcomes "
    "over abstract praise."
)

_RULES_TAILORING = (
    " Tailoring: match qualifications directly to the posting, "
    "incorporate its keywords naturally, emphasize the candidate's "
    "strongest aligned experience, and address the employer's likely "
    "priorities. Never fabricate experience, metrics, or company facts "
    "that are not in the inputs."
)

_RULES_ANTI_SLOP = (
    " Additional AI-slop guardrails (style only, add no facts), "
    "distilled from the no-ai-slop skill: apply the portability test to "
    "every sentence - if it could move unchanged to another person, "
    "company, or product, cut it or replace it with a specific fact "
    "already in the truth. Show, don't tell: never label a point as "
    "important, notable, key, or worth noting, let the fact carry the "
    "weight. Do not use weasel attribution such as industry-leading, "
    "widely regarded as, world-class, or experts agree. Prefer a "
    "concrete, direct verb over an abstraction (write 'tracks sponsors, "
    "drafts, and due dates' rather than 'serves as a centralized hub for "
    "sponsor management'). Do not rotate synonyms for the same thing "
    "across sentences; repeat the clear word instead. Do not use "
    "vague-scale words such as significantly, substantially, various, or "
    "numerous, or 'a wide range of' in place of a number, unless that "
    "number is present in the referenced fact. Do not use negative "
    "listing ('not a X, not a Y, a Z') and do not use rhetorical setups. "
    "Do not end with a summary-recap paragraph (In conclusion, "
    "Ultimately, Overall, or a final paragraph that restates the "
    "letter); end on the last concrete point or a plain next step. Do "
    "not close with a fake-profound metaphor or aphorism. Avoid hollow "
    "adverbs in the letter: successfully, effectively, efficiently, "
    "strategically, proactively."
)

_RULES_LETTER_STYLE = (
    " STYLE (phrasing only, add no facts): keep the letter to one page. "
    "Address a specific named recipient when one is known, otherwise use "
    "a role-appropriate greeting. Tailor to this specific organization "
    "and posting: reference the skills and requirements it names and "
    "draw explicit connections to the candidate's real experience. Write "
    "in natural first person and vary sentence rhythm; open with a hook "
    "that earns attention, never a template like 'I am writing to apply "
    "for'. Between the factual claims, write with genuine voice and "
    "specific interest in this role (the connective narrative is where "
    "the letter comes alive), but keep every concrete example anchored "
    "to a fact from the candidate's truth. The candidate's own name is "
    "printed in the letterhead above the body, so NEVER write the "
    "candidate's name in the letter text: do not name the candidate in "
    "the opening and do not add a signature or sign-off line with the "
    "candidate's name at the end. Structure: an opening that names the "
    "role and gives a reason to read on, then 1-2 body paragraphs of "
    "concrete supporting examples drawn ONLY from the facts, then a "
    "brief, forward-looking close."
)

_LEGACY_TAIL = (
    _STRUCTURE
    + _OPENER
    + _RULES_CAREER_SERVICES
    + _RULES_TAILORING
    + _RULES_ANTI_SLOP
    + _RULES_LETTER_STYLE
    + GUARDRAIL_CONTRACT
)

LEGACY_PROFESSIONAL = _FRAMING_STANDARD + _VOICE_PROFESSIONAL + _LEGACY_TAIL
LEGACY_WARM = _FRAMING_STANDARD + _VOICE_WARM + _LEGACY_TAIL
LEGACY_CONCISE = _FRAMING_STANDARD + _VOICE_CONCISE + _LEGACY_TAIL


def _sentence_set(text: str) -> set[str]:
    return set(text.split(". "))


def test_seeded_professional_equivalence():
    preset = SEEDED_PRESETS[0]
    assert preset.id == "professional"
    fragments = seeded_fragments(DEFAULT_CONVENTIONS)
    assembled = assemble_system_prompt(preset, "standard", fragments)
    assert _sentence_set(assembled) == _sentence_set(LEGACY_PROFESSIONAL)


def test_seeded_warm_equivalence():
    preset = next(p for p in SEEDED_PRESETS if p.id == "warm")
    fragments = seeded_fragments(DEFAULT_CONVENTIONS)
    assembled = assemble_system_prompt(preset, "standard", fragments)
    assert _sentence_set(assembled) == _sentence_set(LEGACY_WARM)


def test_seeded_concise_equivalence():
    preset = next(p for p in SEEDED_PRESETS if p.id == "concise")
    fragments = seeded_fragments(DEFAULT_CONVENTIONS)
    assembled = assemble_system_prompt(preset, "standard", fragments)
    assert _sentence_set(assembled) == _sentence_set(LEGACY_CONCISE)


def test_cover_letter_system_matches_direct_assembly():
    """Sanity check: cover_letter_system_for_preset('professional', ...) takes
    the same path as directly assembling SEEDED_PRESETS[0], so the two agree
    exactly.
    """
    preset = SEEDED_PRESETS[0]
    fragments = seeded_fragments(DEFAULT_CONVENTIONS)
    direct = assemble_system_prompt(preset, "standard", fragments)
    via_helper = cover_letter_system_for_preset("professional", "standard")
    assert direct == via_helper


def test_persistence_round_trip():
    upsert_fragment(Fragment(
        id="test-voice",
        slot="voice",
        title="Test",
        text="Test voice.",
        seeded=False,
    ))
    fragments = list_fragments()
    assert any(f.id == "test-voice" for f in fragments)

    fragment_ids = [
        "test-voice",
        "structure-classic",
        "opener-concrete-hook",
        "rules-career-services-standard",
        "rules-tailoring",
        "rules-anti-slop",
        "rules-letter-style",
    ]
    upsert_preset(Preset(
        id="test-preset",
        name="Test",
        fragment_ids=fragment_ids,
        seeded=False,
    ))
    presets = list_presets()
    assert any(p.id == "test-preset" for p in presets)


def test_recommended_flag_on_seeded_fragments():
    """Verify exactly the four rules-* fragments are marked recommended."""
    recommended_ids = {f.id for f in SEEDED_FRAGMENTS if f.recommended}
    expected = {"rules-career-services-standard", "rules-tailoring", "rules-anti-slop", "rules-letter-style"}
    assert recommended_ids == expected


def test_recommended_round_trip():
    """Verify recommended flag round-trips through to_dict/from_dict."""
    frag_true = Fragment(id="test-rec-true", slot="voice", title="T", text="T.", recommended=True)
    dict_form = frag_true.to_dict()
    restored = Fragment.from_dict(dict_form)
    assert restored.recommended is True

    frag_false = Fragment(id="test-rec-false", slot="voice", title="F", text="F.", recommended=False)
    dict_form = frag_false.to_dict()
    restored = Fragment.from_dict(dict_form)
    assert restored.recommended is False


def test_recommended_defaults_to_false():
    """Verify from_dict without recommended key defaults to False."""
    d = {
        "id": "test-no-rec",
        "slot": "voice",
        "title": "No Rec",
        "text": "Text.",
        "seeded": False,
    }
    frag = Fragment.from_dict(d)
    assert frag.recommended is False


def test_user_fragment_recommended_persists_false():
    """Verify upsert_fragment/list_fragments round-trips user fragment with default recommended."""
    user_frag = Fragment(id="user-voice", slot="voice", title="User", text="User voice.")
    upsert_fragment(user_frag)
    fragments = list_fragments()
    persisted = next(f for f in fragments if f.id == "user-voice")
    assert persisted.recommended is False



def test_preset_may_hold_two_fragments_in_one_slot():
    """Slots are a display grouping: a preset may combine several voices."""
    upsert_fragment(Fragment(id="voice-a", slot="voice", title="A", text="Voice A."))
    upsert_fragment(Fragment(id="voice-b", slot="voice", title="B", text="Voice B."))
    upsert_preset(Preset(
        id="two-voices",
        name="Two voices",
        fragment_ids=["voice-a", "voice-b", "structure-classic", "opener-concrete-hook"],
    ))
    stored = get_preset("two-voices")
    assert stored.fragment_ids[:2] == ["voice-a", "voice-b"]


def test_list_fragments_honours_conventions():
    """list_fragments renders the seeded fragments for the given conventions."""
    custom = CvConventions(letter_paragraphs_min=2, letter_paragraphs_max=9)
    structure = next(f for f in list_fragments(custom) if f.id == "structure-classic")
    assert "2 to 9" in structure.text
    default_structure = next(f for f in list_fragments() if f.id == "structure-classic")
    assert "3 to 5" in default_structure.text


def test_set_default_preset_does_not_persist_seeded_presets():
    set_default_preset("warm")
    assert not (data_dir() / PRESETS_FILE).exists()
    assert default_preset().id == "warm"
    assert [p.is_default for p in list_presets() if p.id != "warm"] == [False, False]


def test_set_default_preset_on_user_preset():
    upsert_preset(Preset(
        id="user-default",
        name="User default",
        fragment_ids=["voice-professional", "structure-classic"],
    ))
    set_default_preset("user-default")
    assert default_preset().id == "user-default"
    records = json.loads((data_dir() / PRESETS_FILE).read_text(encoding="utf-8"))
    assert {r["id"] for r in records} == {"user-default"}


def test_set_default_preset_rejects_unknown_id():
    with pytest.raises(KeyError):
        set_default_preset("nope")


def test_legacy_persisted_seeded_presets_are_ignored_but_default_survives():
    """A pre-existing record with a seeded id must not shadow the code definition."""
    (data_dir() / PRESETS_FILE).write_text(json.dumps([
        {
            "id": "warm",
            "name": "Stale warm",
            "fragment_ids": ["voice-warm"],
            "is_default": True,
            "seeded": True,
        }
    ]), encoding="utf-8")
    warm = get_preset("warm")
    assert warm.name == "Warm"
    assert len(warm.fragment_ids) > 1
    assert warm.is_default is True
    assert default_preset().id == "warm"


def test_legacy_user_preset_default_survives_the_marker_migration():
    """An operator whose default was a USER preset keeps it after upgrading.

    Old versions recorded the default only as is_default on the persisted
    records; the seeded "professional" record ships is_default=True, so a
    migration that ignored user records would silently revert the choice.
    """
    (data_dir() / PRESETS_FILE).write_text(json.dumps([
        {"id": "professional", "name": "Professional", "fragment_ids": ["voice-professional"],
         "is_default": False, "seeded": True},
        {"id": "mine", "name": "Mine", "fragment_ids": ["voice-warm", "structure-classic"],
         "is_default": True, "seeded": False},
    ]), encoding="utf-8")
    assert default_preset().id == "mine"
    assert [p.id for p in list_presets() if p.is_default] == ["mine"]


def test_stale_marker_does_not_mask_the_legacy_default():
    """A marker naming a preset that no longer exists falls through, not back."""
    (data_dir() / PRESETS_FILE).write_text(json.dumps([
        {"id": "mine", "name": "Mine", "fragment_ids": ["voice-warm"],
         "is_default": True, "seeded": False},
    ]), encoding="utf-8")
    (data_dir() / "prompt_default.json").write_text(
        json.dumps({"presetId": "deleted-preset"}), encoding="utf-8"
    )
    assert default_preset().id == "mine"


def test_default_preset_fallback_is_a_copy_of_the_seeded_preset():
    """Mutating the returned preset must not corrupt SEEDED_PRESETS process-wide."""
    (data_dir() / PRESETS_FILE).write_text(json.dumps([
        {"id": "professional", "name": "Professional", "fragment_ids": ["voice-professional"],
         "is_default": False, "seeded": True},
    ]), encoding="utf-8")
    preset = default_preset()
    assert preset.id == "professional"
    preset.fragment_ids.append("intruder")
    assert "intruder" not in next(p for p in SEEDED_PRESETS if p.id == "professional").fragment_ids


def test_voice_override_emitted_once_for_multiple_voice_fragments():
    upsert_fragment(Fragment(id="voice-a", slot="voice", title="A", text="Voice A."))
    upsert_fragment(Fragment(id="voice-b", slot="voice", title="B", text="Voice B."))
    preset = Preset(
        id="two-voices",
        name="Two voices",
        fragment_ids=["voice-a", "voice-b", "structure-classic"],
    )
    assembled = assemble_system_prompt(
        preset, "standard", list_fragments(), voice_override="brisk"
    )
    assert assembled.count(" Voice: brisk.") == 1
    assert "Voice A." not in assembled
    assert "Voice B." not in assembled


def test_seeded_fragments_cannot_be_edited():
    with pytest.raises(ValueError):
        upsert_fragment(Fragment(
            id="voice-professional",
            slot="voice",
            title="Overridden",
            text="Should not stick.",
        ))


def test_seeded_fragments_cannot_be_deleted():
    with pytest.raises(ValueError):
        delete_fragment("voice-professional")


def test_seeded_presets_cannot_be_edited():
    with pytest.raises(ValueError):
        upsert_preset(Preset(
            id="professional",
            name="Overridden",
            fragment_ids=["voice-professional", "structure-classic", "opener-concrete-hook"],
        ))


def test_seeded_presets_cannot_be_deleted():
    with pytest.raises(ValueError):
        delete_preset("professional")


def test_cannot_delete_referenced_fragment():
    fragment = Fragment(id="test-voice-ref", slot="voice", title="Ref", text="Voice ref.")
    upsert_fragment(fragment)
    upsert_preset(Preset(
        id="test-preset-ref",
        name="Ref preset",
        fragment_ids=[
            fragment.id,
            "structure-classic",
            "opener-concrete-hook",
            "rules-career-services-standard",
        ],
    ))
    with pytest.raises(ValueError) as excinfo:
        delete_fragment(fragment.id)
    assert "test-preset-ref" in str(excinfo.value)


def test_default_preset_fallback():
    # No presets.json has been written in this isolated data_dir, so
    # default_preset() must fall back to the seeded professional preset.
    preset = default_preset()
    assert preset.id == "professional"
    assert preset.is_default is True


def test_assembled_prompt_always_ends_with_guardrail():
    fragment = Fragment(id="user-voice", slot="voice", title="User", text="User voice.")
    upsert_fragment(fragment)
    preset = Preset(
        id="user-preset",
        name="User preset",
        fragment_ids=[
            fragment.id,
            "structure-classic",
            "opener-concrete-hook",
            "rules-career-services-standard",
        ],
    )
    fragments = list_fragments()
    assembled = assemble_system_prompt(preset, "standard", fragments)
    assert assembled.endswith(GUARDRAIL_CONTRACT)
