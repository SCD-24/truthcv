"""Assembles a cover-letter system prompt from ordered fragments.

The prompt is framing (persona/length) + slot-ordered fragments (voice,
structure, opener, rules) + the fixed guardrail contract that makes the
model tag every factual claim so the guardrail can validate it. Fragment
selection and ordering are entirely data-driven via a ``Preset``; this
module only knows how to lay pieces out, never what they say.
"""

from __future__ import annotations

from .fragments import Fragment, Preset, SLOTS

GUARDRAIL_CONTRACT = (
    " Guardrail contract: every sentence that states a FACT about the candidate "
    "(employer, title, date, metric, skill, achievement) must list that fact "
    "verbatim in its 'claims'. Never invent a fact absent from the candidate's "
    "truth. Connective and interpretive sentences carry no claims, that is where "
    "your voice lives, so use them freely."
)


def framing(length: str) -> str:
    """The opening persona/length sentence every cover letter system prompt starts with."""
    return (
        f"You are writing a compelling, {length.lower()}-length cover letter that "
        "makes a hiring manager want to meet this candidate. Write a genuine, engaging "
        "letter with a clear throughline about why this candidate fits this specific "
        "role, not a dry recitation of facts."
    )


def assemble_system_prompt(
    preset: Preset,
    length: str,
    fragments: list[Fragment],
    voice_override: str | None = None,
) -> str:
    """Assemble a cover-letter system prompt from ``preset``'s fragments.

    Fragments are ordered by slot (voice, structure, opener, rules) and,
    within a slot, by their appearance in ``preset.fragment_ids``. When
    ``voice_override`` is given it replaces the voice fragment's text with a
    plain ``" Voice: {override}."`` sentence instead of the fragment's own
    text, letting a caller supply a free-form tone the fragment store does
    not have a fragment for.
    """
    fragments_by_id = {f.id: f for f in fragments}
    ordered: list[Fragment] = []
    for slot in SLOTS:
        for fragment_id in preset.fragment_ids:
            fragment = fragments_by_id.get(fragment_id)
            if fragment is not None and fragment.slot == slot:
                ordered.append(fragment)

    pieces = [framing(length)]
    for fragment in ordered:
        if voice_override is not None and fragment.slot == "voice":
            pieces.append(f" Voice: {voice_override}.")
        else:
            pieces.append(f" {fragment.text}")
    pieces.append(GUARDRAIL_CONTRACT)
    return "".join(pieces)
