"""Prompts served for the Cover Letter Engine.

The system prompt makes the model tag every factual sentence's claims so the
guardrail can validate ONLY those claims against the truth store; connective
narrative is free. The facts block renders the candidate's whole career as plain
text (a cover letter weaves the full history, unlike the id-referenced CV).
"""

from __future__ import annotations

from truth.model import Truth

from .style import LETTER_STYLE


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
    "empty enthusiasm. Keep it to 3 to 5 short paragraphs, under one page. "
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


def cover_letter_system(tone: str, length: str) -> str:
    """System prompt: write an engaging, guardrail-truthful cover letter to elite
    career-services standards in the requested voice, tagging every factual claim
    verbatim so it can be validated."""
    direction = _TONE_DIRECTION.get(tone.lower(), _TONE_DIRECTION["professional"])
    return (
        f"You are writing a compelling, {length.lower()}-length cover letter that "
        "makes a hiring manager want to meet this candidate. Write a genuine, engaging "
        "letter with a clear throughline about why this candidate fits this specific "
        "role, not a dry recitation of facts."
        + _WRITING_STANDARD
        + direction
        + LETTER_STYLE
        + _ANTI_TELL_RULES
        + " Guardrail contract: every sentence that states a FACT about the candidate "
        "(employer, title, date, metric, skill, achievement) must list that fact "
        "verbatim in its 'claims'. Never invent a fact absent from the candidate's "
        "truth. Connective and interpretive sentences carry no claims, that is where "
        "your voice lives, so use them freely."
    )


def cover_letter_facts_block(truth: Truth) -> str:
    """Render the candidate's whole career (experiences, education, skills) as the
    plain-text CANDIDATE FACTS the letter may draw from."""
    lines: list[str] = []
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
    return "\n".join(lines)
