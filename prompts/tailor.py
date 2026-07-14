"""Prompts served for the Tailor Engine: keyword extraction, missing-qualification
inference, and CV selection/rephrasing.

Two truth-block builders live here and render the same truth differently on
purpose: ``infer_truth_block`` omits ids/dates (the inference step only reasons
about content), while ``select_truth_block`` includes every id and date range
(the selection step references facts strictly by id). They are NOT merged.
"""

from __future__ import annotations

from truth.model import Truth

from .style import CV_STYLE


# --- Keyword extraction -----------------------------------------------------

def keywords_system() -> str:
    """System prompt: pull screenable keywords out of a job posting.

    Restricted to real, screenable skills because these keywords later drive both
    the inference step and the ATS 'missing keyword' review — feeding in job
    titles or locations there would flag the CV for things a CV body should never
    contain (nobody writes 'Remote in Germany' as a skill).
    """
    return (
        "Extract ONLY the concrete, screenable skills a candidate is judged on from "
        "this job posting: technologies, tools, programming languages, frameworks, "
        "platforms, methodologies, and hard requirements (e.g. specific certifications "
        "or years with a named tool). Return a deduplicated list of short keyword "
        "phrases.\n"
        "EXCLUDE, do not return any of these: job titles and seniority labels (e.g. "
        "'Senior Data Engineer', 'Lead', 'Junior'); locations and work arrangement "
        "(e.g. 'Remote in Germany', 'hybrid', 'onsite', 'relocation', city or country "
        "names); company or team names; salary, benefits, and perks; and generic soft "
        "phrases (e.g. 'team player', 'fast-paced environment', 'communication "
        "skills'). Do not invent anything not implied by the text."
    )


# --- Missing-qualification inference ----------------------------------------

def infer_system() -> str:
    """System prompt: surface truthful, inferable skills for the user to confirm.

    This is the ONLY stage allowed to relabel real experience in the posting's
    vocabulary (selection never adds information). It exists so a keyword the
    candidate can legitimately claim — 'ETL' for someone whose bullets describe
    moving data between systems — reaches the confirmation gate instead of being
    silently dropped. Keyword-driven so real coverage gaps get proposed, and
    strictly gated so nothing unsupported is ever invented.
    """
    return (
        "You are given a job posting's keywords and a candidate's existing verified "
        "experiences (each with an id and its bullets).\n"
        "Walk through EACH keyword that is NOT already present in the facts and decide "
        "whether an existing experience bullet genuinely SUPPORTS or IMPLIES it. "
        "Examples of legitimate support: a bullet describing moving or converting data "
        "between systems supports 'ETL' and 'Data transformation'; building checks on "
        "input data supports 'Data validation'; tuning a system for speed supports "
        "'Performance optimization'.\n"
        "When (and only when) a bullet genuinely supports the keyword, propose it as an "
        "inference: give the claim phrased in the posting's vocabulary, a short "
        "rationale naming the real experience that implies it, and the experienceId of "
        "the job it belongs to.\n"
        "HARD RULES: these are PROPOSALS the candidate must confirm, not facts. NEVER "
        "invent experience the bullets do not support — if no bullet implies a keyword, "
        "omit it. Do not repeat anything already stated in the facts. Only relabel or "
        "generalize what the existing bullets genuinely imply; the goal is to surface "
        "truthful, defensible skills the candidate can legitimately claim, never to "
        "stuff unsupported keywords."
    )


def infer_truth_block(truth: Truth) -> str:
    """Render experiences (id + role/company + bullets) and skills for inference.

    Deliberately omits dates and bullet ids — the inference step reasons about
    content, not identity.
    """
    lines: list[str] = ["EXPERIENCES:"]
    for e in truth.experiences:
        lines.append(f"[{e.id}] {e.role} — {e.company}")
        for b in e.bullets:
            lines.append(f"    - {b.value}")
    if truth.skills:
        lines.append("SKILLS: " + ", ".join(s.value for s in truth.skills))
    return "\n".join(lines)


# --- CV selection / rephrasing ----------------------------------------------

# The craft standard the CV is written to: elite career-services quality. Style
# only; adds no facts and never overrides the id contract below.
_CV_STANDARD = (
    " You write to elite university career-services standards: a polished, "
    "ATS-friendly CV that is concise, results-oriented, and easy to skim. Make it "
    "achievement-focused, not responsibility-focused, and written for recruiters who "
    "scan quickly: specific rather than general, active rather than passive, and "
    "fact-based with quantified outcomes wherever the referenced fact supports them. "
    "No personal pronouns. No narrative paragraphs in experience sections. Start "
    "every bullet with a strong action verb (built, led, shipped, owned, cut, raised, "
    "designed, implemented, streamlined). Keep bullets concise and impact-oriented; "
    "cut filler and redundancy; drop empty, placeholder, or weak entries. Keep each "
    "section in reverse chronological order with consistent formatting. Each role "
    "gets 2 to 6 bullets, each showing a measurable outcome where the facts allow and "
    "demonstrating leadership, technical ability, communication, analysis, ownership, "
    "or problem-solving. Group skills by category (languages, frameworks, cloud "
    "platforms, databases, tools, analytics, certifications) when the facts permit. "
    "Prioritize the experiences most relevant to the posting, reorder bullets for "
    "strongest alignment, and incorporate the posting's important keywords naturally "
    "where a real fact backs them."
)


# Constraints that remove the common markers of AI-written prose. Purely
# mechanical style rules; no facts.
_CV_ANTI_TELL_RULES = (
    " Hard style constraints: Do NOT use em dashes or en dashes in bullet text. Use "
    "commas, parentheses, or semicolons, or split into two sentences. (Structured "
    "date ranges are exempt.) Use straight quotes (' and \"), never curly quotes. Do "
    "not use these words: leverage, delve, foster, unlock, harness, navigate, "
    "spearhead, orchestrate, robust, comprehensive, seamless, vibrant, intricate, "
    "transformative, synergy, paradigm, tapestry, ecosystem (as metaphor), holistic, "
    "innovative; prefer plainer verbs (built, led, shipped, owned, cut, raised, "
    "fixed). Avoid hollow adverbs in bullets: successfully, effectively, efficiently, "
    "strategically, proactively. Avoid contrastive cliches such as 'not just X, but "
    "Y'. Prefer concrete numbers and outcomes over abstract praise."
)


def select_system() -> str:
    """System prompt: choose, order, and lightly rephrase facts by id (+ CV style)."""
    return (
        "You tailor a CV to a job posting using ONLY the candidate's verified facts. "
        "You are given experiences (each with an id and bullets that each have an id) "
        "and skills (each with an id). Choose and order the experiences and bullets "
        "most relevant to the posting, and lightly rephrase each chosen bullet for "
        "impact. Choose the relevant skills by id. RULES: (1) reference ONLY the "
        "provided ids; (2) a bullet id must stay under the experience it was given "
        "with, never move a bullet to another job; (3) NEVER invent a fact, number, "
        "employer, or date; rephrasing must not add information. Do not touch roles, "
        "companies, or dates, those are fixed."
        + _CV_STANDARD
        + CV_STYLE
        + _CV_ANTI_TELL_RULES
    )


def _dates(start: str, end: str) -> str:
    """Format a date range with a spaced en-dash so it tokenizes to separate
    year tokens for the guardrail (a plain hyphen would read as one token)."""
    start, end = start.strip(), end.strip()
    if start and end:
        return f"{start} – {end}"
    return start or end


def select_truth_block(truth: Truth) -> str:
    """Render experiences and skills WITH ids and date ranges for id-based selection."""
    lines: list[str] = ["EXPERIENCES:"]
    for e in truth.experiences:
        lines.append(f"[{e.id}] {e.role} — {e.company} ({_dates(e.start, e.end)})")
        for b in e.bullets:
            lines.append(f"    - [{b.id}] {b.value}")
    if truth.skills:
        lines.append("SKILLS:")
        lines.extend(f"[{s.id}] {s.value}" for s in truth.skills)
    return "\n".join(lines)
