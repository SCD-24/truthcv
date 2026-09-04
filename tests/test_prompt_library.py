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

import pytest

from prompts.assemble import GUARDRAIL_CONTRACT, assemble_system_prompt
from prompts.coverletter import cover_letter_system
from prompts.fragments import (
    DEFAULT_CONVENTIONS,
    EXCLUSIVE_SLOTS,
    Fragment,
    Preset,
    SEEDED_FRAGMENTS,
    SEEDED_PRESETS,
    SLOTS,
    seeded_fragments,
)
from prompts.library import (
    Conflict,
    PresetConflictError,
    default_preset,
    delete_fragment,
    delete_preset,
    get_fragment,
    get_preset,
    list_fragments,
    list_presets,
    upsert_fragment,
    upsert_preset,
    validate_preset,
)


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
    """Sanity check: cover_letter_system('professional', ...) takes the same
    path as directly assembling SEEDED_PRESETS[0], so the two agree exactly.
    """
    preset = SEEDED_PRESETS[0]
    fragments = seeded_fragments(DEFAULT_CONVENTIONS)
    direct = assemble_system_prompt(preset, "standard", fragments)
    via_helper = cover_letter_system("professional", "standard")
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


def test_validate_preset_exclusive_slot_conflict():
    frag1 = Fragment(id="voice-a", slot="voice", title="A", text="Voice A.")
    frag2 = Fragment(id="voice-b", slot="voice", title="B", text="Voice B.")
    upsert_fragment(frag1)
    upsert_fragment(frag2)
    conflicts = validate_preset([
        frag1.id,
        frag2.id,
        "structure-classic",
        "opener-concrete-hook",
        "rules-career-services-standard",
    ])
    exclusive = [c for c in conflicts if c.kind == "exclusive_slot"]
    assert len(exclusive) == 1
    conflict = exclusive[0]
    assert conflict.slot == "voice"
    assert frag1.id in conflict.message
    assert frag2.id in conflict.message


def test_validate_preset_declared_conflict():
    frag1 = Fragment(
        id="rules-x",
        slot="rules",
        title="X",
        text="Rule X.",
        conflicts_with=["rules-y"],
    )
    frag2 = Fragment(id="rules-y", slot="rules", title="Y", text="Rule Y.")
    upsert_fragment(frag1)
    upsert_fragment(frag2)
    conflicts = validate_preset([
        "voice-professional",
        "structure-classic",
        "opener-concrete-hook",
        frag1.id,
        frag2.id,
    ])
    declared = [c for c in conflicts if c.kind == "declared"]
    assert len(declared) >= 1


def test_validate_preset_unknown_fragment():
    conflicts = validate_preset(["unknown_id"])
    assert len(conflicts) == 1
    assert conflicts[0].kind == "unknown_fragment"


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
