"""Fragment and Preset data model for the operator-configurable prompt store.

A ``Fragment`` is one swappable slice of prompt guidance (a voice, a
structure, an opener convention, or a style/rules rule). A ``Preset`` names a
set of fragment ids an operator can select together in one action. The
SEEDED_* constants below reproduce, byte-for-byte in spirit, the guidance that
used to live as fixed literals in ``prompts/coverletter.py`` and
``prompts/style.py``, split at sentence boundaries so each piece can be
swapped independently. Splitting existing prose into fragments changes
nothing about what is sent to the model until an operator actually swaps a
fragment out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .conventions import CvConventions, DEFAULT_CONVENTIONS
from .style import letter_anti_slop, letter_style


SLOTS: tuple[str, ...] = ("voice", "structure", "opener", "rules")
"""The recognised fragment slots.

Every ``Fragment.slot`` must be one of these four. ``voice`` picks the letter's
tone, ``structure`` picks the paragraph plan, ``opener`` picks how the first
paragraph is framed, and ``rules`` holds additive style/behaviour constraints
that are not mutually exclusive with one another.
"""

EXCLUSIVE_SLOTS: set[str] = {"voice", "structure", "opener"}
"""Slots where a preset may select at most one fragment.

``rules`` is deliberately excluded: an operator may want several rules
fragments active at once (career-services standard, tailoring, anti-slop,
letter style), whereas selecting two voices or two structures at the same
time would be contradictory guidance sent to the model.
"""


@dataclass
class Fragment:
    """One swappable slice of prompt guidance.

    ``id`` is the stable identifier referenced by presets and by the ORM/DB
    layer built on top of this model. ``slot`` places it in one of ``SLOTS``.
    ``seeded`` marks a fragment that shipped with the product rather than one
    an operator authored. ``recommended`` marks a fragment that a preset should
    include; UI warnings (non-blocking) appear when a preset omits any
    recommended fragment. ``conflicts_with`` lists other fragment ids this
    fragment should not be combined with, independent of slot exclusivity.
    """

    id: str
    slot: str
    title: str
    text: str
    seeded: bool = False
    recommended: bool = False
    conflicts_with: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Render this fragment as a plain ``dict`` suitable for JSON/YAML."""
        return {
            "id": self.id,
            "slot": self.slot,
            "title": self.title,
            "text": self.text,
            "seeded": self.seeded,
            "recommended": self.recommended,
            "conflicts_with": list(self.conflicts_with),
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Fragment":
        """Reconstruct a ``Fragment`` from ``to_dict`` output (or equivalent).

        Raises ``ValueError`` if ``slot`` is not one of ``SLOTS`` — an
        unrecognised slot is a data error, not something to silently coerce.
        """
        slot = d["slot"]
        if slot not in SLOTS:
            raise ValueError(f"unknown fragment slot: {slot!r} (expected one of {SLOTS})")
        return Fragment(
            id=d["id"],
            slot=slot,
            title=d["title"],
            text=d["text"],
            seeded=bool(d.get("seeded", False)),
            recommended=bool(d.get("recommended", False)),
            conflicts_with=list(d.get("conflicts_with", [])),
        )


@dataclass
class Preset:
    """A named, orderable set of fragment ids an operator can pick as a unit.

    ``is_default`` marks the preset applied when an operator has not chosen
    one. ``seeded`` marks a preset that shipped with the product.
    """

    id: str
    name: str
    fragment_ids: list[str]
    is_default: bool = False
    seeded: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Render this preset as a plain ``dict`` suitable for JSON/YAML."""
        return {
            "id": self.id,
            "name": self.name,
            "fragment_ids": list(self.fragment_ids),
            "is_default": self.is_default,
            "seeded": self.seeded,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Preset":
        """Reconstruct a ``Preset`` from ``to_dict`` output (or equivalent).

        Raises ``ValueError`` if ``fragment_ids`` is missing, empty, or
        contains anything other than non-empty strings — a preset that
        selects no fragments (or a malformed id) is a data error.
        """
        fragment_ids = d.get("fragment_ids")
        if not fragment_ids:
            raise ValueError("preset fragment_ids must be a non-empty list")
        for fid in fragment_ids:
            if not isinstance(fid, str) or not fid:
                raise ValueError(f"preset fragment_ids must all be non-empty strings, got {fid!r}")
        return Preset(
            id=d["id"],
            name=d["name"],
            fragment_ids=list(fragment_ids),
            is_default=bool(d.get("is_default", False)),
            seeded=bool(d.get("seeded", False)),
        )


# --- Text bodies below are split, at sentence boundaries, from the fixed
# literals that used to live in prompts/coverletter.py (_TONE_DIRECTION,
# _WRITING_STANDARD) and prompts/style.py (letter_style, letter_anti_slop).
# Splitting them into fragments changes no default output; it only makes each
# piece independently swappable.

_STRUCTURE_SENTENCE = (
    "Structure: an opening paragraph that names the role, gives a specific "
    "concrete hook tied to the company or posting, and surfaces the strongest "
    "qualification; middle paragraph(s) that connect past accomplishments to "
    "the employer's likely needs, reference specific projects or outcomes, and "
    "show understanding of the company's goals or industry; and a closing "
    "paragraph that briefly reaffirms fit, states the ability to contribute, "
    "thanks the reader, and ends professionally."
)

_OPENER_SENTENCE = (
    "Open with a paragraph that names the role, gives a specific concrete hook "
    "tied to the company or posting, and surfaces the strongest qualification."
)

_CAREER_SERVICES_INTRO = (
    "You are a professional career writer trained to elite university "
    "career-services standards. Produce a tailored, compelling, concise letter "
    "that is personalized to the target company and role, shows real "
    "understanding of the organization, and connects the candidate's "
    "background to the employer's needs. Highlight relevant accomplishments "
    "and transferable skills. Sound confident, articulate, and professional; "
    "avoid generic phrasing and empty enthusiasm. Principles: clear, direct "
    "prose in active voice; prioritize evidence and examples over claims; show "
    "impact through measurable outcomes when the facts support them; do not "
    "repeat the resume verbatim, reframe achievements toward the employer's "
    "needs; keep the tone natural, not robotic; and go easy on the word 'I', "
    "focusing on value to the employer rather than the candidate's wishes."
)

_ANTI_TELL_RULES_TEXT = (
    "Hard style constraints: Do NOT use em dashes or en dashes. Use commas, "
    "parentheses, or semicolons, or split into two sentences. Use straight "
    "quotes (' and \"), never curly quotes. Do not open with 'I am thrilled', "
    "'excited', 'delighted', 'writing to express my interest', 'I hope this "
    "letter finds you well', or 'As a [adjective] professional with X years'; "
    "open with a specific concrete hook tied to the posting or company. Do not "
    "use these words: leverage, delve, foster, unlock, harness, navigate, "
    "spearhead, orchestrate, robust, comprehensive, seamless, vibrant, "
    "intricate, transformative, synergy, paradigm, tapestry, ecosystem (as "
    "metaphor), holistic, innovative, passionate, dynamic. Avoid contrastive "
    "cliches such as 'not just X, but Y' or 'it's not merely A, it's B'. Avoid "
    "stock closers like 'I look forward to the opportunity to discuss how my "
    "skills can contribute to your team's success'; close briefly and "
    "directly. Prefer short, varied sentences; avoid rule-of-three lists when "
    "one or two items say it better. Prefer concrete numbers and outcomes over "
    "abstract praise."
)

_TAILORING_SENTENCE = (
    "Tailoring: match qualifications directly to the posting, incorporate its "
    "keywords naturally, emphasize the candidate's strongest aligned "
    "experience, and address the employer's likely priorities. Never "
    "fabricate experience, metrics, or company facts that are not in the "
    "inputs."
)

_VOICE_TEXT = {
    "voice-professional": (
        "Voice: confident and polished, measured, businesslike, and "
        "self-assured without stiffness, letting concrete results speak."
    ),
    "voice-warm": (
        "Voice: warm and personable, genuinely engaged and human, writing "
        "about why this role and organization fit the candidate."
    ),
    "voice-concise": (
        "Voice: tight and direct. Every sentence earns its place, short and "
        "specific with no filler, while still reading as a real person, not a "
        "list."
    ),
}


def seeded_fragments(conventions: CvConventions = DEFAULT_CONVENTIONS) -> list[Fragment]:
    """Build the fragments TruthCV ships with, rendered for ``conventions``.

    The voice, opener, and rules fragments are fixed prose; the structure
    fragment and the letter-style rules fragment are rendered from
    ``conventions`` so a non-default ``CvConventions`` produces different
    fragment text without any caller having to edit this module.
    """
    paragraph_guidance = (
        f"Keep it to {conventions.letter_paragraphs_min} to "
        f"{conventions.letter_paragraphs_max} short paragraphs, under "
        f"{conventions.page_target}."
    )
    return [
        Fragment(
            id="voice-professional",
            slot="voice",
            title="Professional",
            text=_VOICE_TEXT["voice-professional"],
            seeded=True,
        ),
        Fragment(
            id="voice-warm",
            slot="voice",
            title="Warm",
            text=_VOICE_TEXT["voice-warm"],
            seeded=True,
        ),
        Fragment(
            id="voice-concise",
            slot="voice",
            title="Concise",
            text=_VOICE_TEXT["voice-concise"],
            seeded=True,
        ),
        Fragment(
            id="structure-classic",
            slot="structure",
            title="Classic three-part structure",
            text=f"{paragraph_guidance} {_STRUCTURE_SENTENCE}",
            seeded=True,
        ),
        Fragment(
            id="opener-concrete-hook",
            slot="opener",
            title="Concrete hook opener",
            text=_OPENER_SENTENCE,
            seeded=True,
        ),
        Fragment(
            id="rules-career-services-standard",
            slot="rules",
            title="Career-services writing standard",
            text=f"{_CAREER_SERVICES_INTRO} {_ANTI_TELL_RULES_TEXT}",
            seeded=True,
            recommended=True,
        ),
        Fragment(
            id="rules-tailoring",
            slot="rules",
            title="Tailoring to the posting",
            text=_TAILORING_SENTENCE,
            seeded=True,
            recommended=True,
        ),
        Fragment(
            id="rules-anti-slop",
            slot="rules",
            title="Anti-slop guardrails",
            text=letter_anti_slop().strip(),
            seeded=True,
            recommended=True,
        ),
        Fragment(
            id="rules-letter-style",
            slot="rules",
            title="Letter style",
            text=letter_style(conventions).strip(),
            seeded=True,
            recommended=True,
        ),
    ]


SEEDED_FRAGMENTS: list[Fragment] = seeded_fragments(DEFAULT_CONVENTIONS)
"""The fragments TruthCV ships with, rendered for ``DEFAULT_CONVENTIONS``."""


def _seeded_preset(preset_id: str, name: str, voice_id: str, is_default: bool = False) -> Preset:
    """Build one of the shipped presets, validating its slot coverage.

    Every seeded preset shares the same structure, opener, and rules
    fragments and differs only by voice; this validates, at import time,
    that the assembled fragment id list has exactly one fragment per
    exclusive slot (``KEY CONSTRAINT``: a preset must never select two
    fragments from the same exclusive slot).
    """
    fragment_ids = [
        voice_id,
        "structure-classic",
        "opener-concrete-hook",
        "rules-career-services-standard",
        "rules-tailoring",
        "rules-anti-slop",
        "rules-letter-style",
    ]
    _assert_one_per_exclusive_slot(fragment_ids)
    return Preset(
        id=preset_id,
        name=name,
        fragment_ids=fragment_ids,
        is_default=is_default,
        seeded=True,
    )


def _assert_one_per_exclusive_slot(fragment_ids: list[str]) -> None:
    """Raise ``ValueError`` unless ``fragment_ids`` has one fragment per exclusive slot."""
    fragments_by_id = {f.id: f for f in SEEDED_FRAGMENTS}
    counts: dict[str, int] = {}
    for fid in fragment_ids:
        slot = fragments_by_id[fid].slot
        if slot in EXCLUSIVE_SLOTS:
            counts[slot] = counts.get(slot, 0) + 1
    for slot in EXCLUSIVE_SLOTS:
        if counts.get(slot, 0) != 1:
            raise ValueError(
                f"preset must select exactly one fragment for exclusive slot "
                f"{slot!r}, got {counts.get(slot, 0)}"
            )


SEEDED_PRESETS: list[Preset] = [
    _seeded_preset("professional", "Professional", "voice-professional", is_default=True),
    _seeded_preset("warm", "Warm", "voice-warm"),
    _seeded_preset("concise", "Concise", "voice-concise"),
]
"""The presets TruthCV ships with: professional (default), warm, and concise.

Each references only fragment ids present in ``SEEDED_FRAGMENTS`` and selects
exactly one fragment per exclusive slot.
"""
