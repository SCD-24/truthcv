"""Prompts served for the Cover Letter Engine.

The system prompt makes the model tag every factual sentence's claims so the
guardrail can validate ONLY those claims against the truth store; connective
narrative is free. The facts block renders the candidate's whole career as plain
text (a cover letter weaves the full history, unlike the id-referenced CV).
"""

from __future__ import annotations

from truth.answers import Answers
from truth.model import Truth

from .conventions import CvConventions, DEFAULT_CONVENTIONS
from .style import letter_style, letter_anti_slop

from prompts.assemble import assemble_system_prompt, GUARDRAIL_CONTRACT, framing
from prompts.fragments import Preset, SEEDED_PRESETS, seeded_fragments
from prompts.library import get_preset, list_fragments


def cover_letter_system(
    tone: str,
    length: str,
    conventions: CvConventions = DEFAULT_CONVENTIONS,
) -> str:
    """System prompt: write an engaging, guardrail-truthful cover letter to elite
    career-services standards in the requested voice, tagging every factual claim
    verbatim so it can be validated.

    The paragraph budget and page target come from ``conventions`` — the
    caller's ``length`` argument shapes the rendered guidance rather than
    being overridden by a hardcoded paragraph count.
    """
    preset = next((p for p in SEEDED_PRESETS if p.id == tone.lower()), None)
    if preset is not None:
        voice_override = None
    else:
        preset = next(p for p in SEEDED_PRESETS if p.is_default)
        voice_override = tone.strip()
    fragments = seeded_fragments(conventions)
    return assemble_system_prompt(preset, length, fragments, voice_override=voice_override)


def cover_letter_system_for_preset(
    preset_id: str | None,
    tone: str,
    length: str,
    conventions: CvConventions = DEFAULT_CONVENTIONS,
) -> str:
    """Use a named preset for the system prompt, falling back to
    cover_letter_system for tone-based selection. tone is passed to
    cover_letter_system only when preset_id is None.
    """
    if preset_id is None:
        return cover_letter_system(tone, length, conventions)
    try:
        preset = get_preset(preset_id)
    except KeyError:
        raise ValueError(f"unknown preset {preset_id}")
    fragments = list_fragments(conventions)
    return assemble_system_prompt(preset, length, fragments, voice_override=None)


def _profile_lines(profile) -> list[str]:
    """Extract non-blank profile header fields for the facts block."""
    lines = []
    if profile.name:
        lines.append(f"Name: {profile.name}")
    if profile.location:
        lines.append(f"Location: {profile.location}")
    if profile.email:
        lines.append(f"Email: {profile.email}")
    if profile.phone:
        lines.append(f"Phone: {profile.phone}")
    for link in profile.links:
        if link.label and link.url:
            lines.append(f"{link.label}: {link.url}")
    if profile.summary:
        lines.append(f"Summary: {profile.summary}")
    return lines


def _answer_lines(answers: Answers | None) -> list[str]:
    """Extract non-blank answer fields for the facts block.

    Excludes canonical_cv_asset_id (internal asset UUID, not a claim).
    """
    if not answers:
        return []
    label_map = {
        "name": "Name",
        "email": "Email",
        "linkedin": "LinkedIn",
        "github": "GitHub",
        "website": "Website",
        "requires_sponsorship": "Requires sponsorship",
        # Neutral label: the operator's work-authorisation status in their own
        # words. The legacy country-specific key maps to the same neutral label
        # so an un-migrated answers.yaml still renders (the truth/answers.py
        # loader migrates its value into work_authorisation_note on load).
        "work_authorisation_note": "Work authorisation",
        "authorized_non_german_country": "Work authorisation",
        "languages": "Languages",
        "highest_relevant_degree": "Highest relevant degree",
        "other_degree": "Other degree",
        "cs_degree": "CS degree",
        "gpa": "GPA",
        "gender": "Gender",
        "years_of_experience": "Years of experience",
        "current_role": "Current role",
        "how_did_you_hear": "How did you hear about us",
        "phone": "Phone",
        "work_authorisation": "Work authorisation",
        "notice_period": "Notice period",
        "location_preference": "Location preference",
    }
    lines = []
    for field_name in [
        f.name for f in Answers.__dataclass_fields__.values()  # type: ignore
    ]:
        if field_name == "canonical_cv_asset_id":
            continue
        value = getattr(answers, field_name, "")
        if value:
            label = label_map.get(field_name, field_name.replace("_", " ").title())
            lines.append(f"{label}: {value}")
    return lines


def cover_letter_facts_block(truth: Truth, answers: Answers | None = None) -> str:
    """Render the candidate's whole career plus profile and screening answers.

    The CANDIDATE FACTS the letter may draw from: experiences, education, skills,
    profile header, and any supplied screening answers (name, email, location,
    years of experience, etc). All facts are plain text, never fabricated.
    """
    lines: list[str] = []
    profile_lines = _profile_lines(truth.profile)
    if profile_lines:
        lines.append("Candidate profile:")
        lines.extend(f"  {line}" for line in profile_lines)
    for e in truth.experiences:
        span = f"{e.start} to {e.end}" if e.start and e.end else (e.start or e.end)
        lines.append(
            f"{e.role} at {e.company} ({span}):"
            if span
            else f"{e.role} at {e.company}:"
        )
        lines.extend(f"  - {b.value}" for b in e.bullets)
    for ed in truth.education:
        span = f"{ed.start} to {ed.end}" if ed.start and ed.end else (ed.start or ed.end)
        lines.append(f"{ed.degree}, {ed.school} ({span})" if span else f"{ed.degree}, {ed.school}")
    if truth.skills:
        lines.append("Skills: " + ", ".join(s.value for s in truth.skills))
    answer_lines = _answer_lines(answers)
    lines.extend(answer_lines)
    return "\n".join(lines)
