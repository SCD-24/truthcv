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


_TONE_DIRECTION = {
    "professional": (
        " Voice: confident and polished, measured, businesslike, and self-assured "
        "without stiffness, letting concrete results speak."
    ),
    "warm": (
        " Voice: warm and personable, genuinely engaged and human, writing about "
        "why this role and organization fit the candidate."
    ),
    "concise": (
        " Voice: tight and direct. Every sentence earns its place, short and "
        "specific with no filler, while still reading as a real person, not a list."
    ),
}


def _tone_direction(tone: str) -> str:
    """The voice guidance for ``tone``.

    A recognised tone maps to its direction; an UNRECOGNISED one is passed
    through as the caller's own words rather than silently rewritten to
    'professional' — the caller may know a tone this module does not, and a
    silent substitution hides the mismatch.
    """
    key = tone.lower()
    if key in _TONE_DIRECTION:
        return _TONE_DIRECTION[key]
    return f" Voice: {tone.strip()}."


# The craft standard the letter is written to: elite career-services quality plus
# hard constraints that strip the usual AI-generated tells. Style only; it adds
# no facts and never overrides the guardrail contract below.
_WRITING_STANDARD = (
    " You are a professional career writer trained to elite university "
    "career-services standards. Produce a tailored, compelling, concise letter "
    "that is personalized to the target company and role, shows real understanding "
    "of the organization, and connects the candidate's background to the "
    "employer's needs. Highlight relevant accomplishments and transferable skills. "
    "Sound confident, articulate, and professional; avoid generic phrasing and "
    "empty enthusiasm. {PARAGRAPH_GUIDANCE} "
    "Principles: clear, direct prose in active voice; prioritize evidence and "
    "examples over claims; show impact through measurable outcomes when the facts "
    "support them; do not repeat the resume verbatim, reframe achievements toward "
    "the employer's needs; keep the tone natural, not robotic; and go easy on the "
    "word 'I', focusing on value to the employer rather than the candidate's "
    "wishes. Structure: an opening paragraph that names the role, gives a specific "
    "concrete hook tied to the company or posting, and surfaces the strongest "
    "qualification; middle paragraph(s) that connect past accomplishments to the "
    "employer's likely needs, reference specific projects or outcomes, and show "
    "understanding of the company's goals or industry; and a closing paragraph that "
    "briefly reaffirms fit, states the ability to contribute, thanks the reader, and "
    "ends professionally. Tailoring: match qualifications directly to the posting, "
    "incorporate its keywords naturally, emphasize the candidate's strongest aligned "
    "experience, and address the employer's likely priorities. Never fabricate "
    "experience, metrics, or company facts that are not in the inputs."
)


# Constraints that remove the common markers of AI-written prose. Purely
# mechanical style rules; no facts.
_ANTI_TELL_RULES = (
    " Hard style constraints: Do NOT use em dashes or en dashes. Use commas, "
    "parentheses, or semicolons, or split into two sentences. Use straight quotes "
    "(' and \"), never curly quotes. Do not open with 'I am thrilled', 'excited', "
    "'delighted', 'writing to express my interest', 'I hope this letter finds you "
    "well', or 'As a [adjective] professional with X years'; open with a specific "
    "concrete hook tied to the posting or company. Do not use these words: "
    "leverage, delve, foster, unlock, harness, navigate, spearhead, orchestrate, "
    "robust, comprehensive, seamless, vibrant, intricate, transformative, synergy, "
    "paradigm, tapestry, ecosystem (as metaphor), holistic, innovative, passionate, "
    "dynamic. Avoid contrastive cliches such as 'not just X, but Y' or 'it's not "
    "merely A, it's B'. Avoid stock closers like 'I look forward to the opportunity "
    "to discuss how my skills can contribute to your team's success'; close briefly "
    "and directly. Prefer short, varied sentences; avoid rule-of-three lists when "
    "one or two items say it better. Prefer concrete numbers and outcomes over "
    "abstract praise."
)


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
    direction = _tone_direction(tone)
    standard = _WRITING_STANDARD.replace(
        "{PARAGRAPH_GUIDANCE}",
        (
            f"Keep it to {conventions.letter_paragraphs_min} to "
            f"{conventions.letter_paragraphs_max} short paragraphs, under "
            f"{conventions.page_target}."
        ),
    )
    return (
        f"You are writing a compelling, {length.lower()}-length cover letter that "
        "makes a hiring manager want to meet this candidate. Write a genuine, engaging "
        "letter with a clear throughline about why this candidate fits this specific "
        "role, not a dry recitation of facts."
        + standard
        + direction
        + letter_style(conventions)
        + _ANTI_TELL_RULES
        + letter_anti_slop()
        + " Guardrail contract: every sentence that states a FACT about the candidate "
        "(employer, title, date, metric, skill, achievement) must list that fact "
        "verbatim in its 'claims'. Never invent a fact absent from the candidate's "
        "truth. Connective and interpretive sentences carry no claims, that is where "
        "your voice lives, so use them freely."
    )


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
