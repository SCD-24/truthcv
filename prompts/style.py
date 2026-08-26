"""Shared CV / cover-letter STYLE guidance injected into generation prompts.

Distilled from docs/reference/cv-style-guidelines.md. This is *style only* —
phrasing, structure, tone, action verbs. It contains NO facts and is NEVER a
source of content: the truthfulness rules in each prompt and the guardrail still
bind. These lines only shape how the user's own verified facts are phrased.

The fixed-constant forms (``CV_STYLE``/``LETTER_STYLE``) are kept because
several callers import them directly; the fragment builders below render the
same text from a CvConventions value object so an operator can change bullet
counts, ordering, page targets, and pronoun policy without touching prompt
prose.

``cv_anti_slop``/``letter_anti_slop`` add a second, independent set of style
bans distilled from the no-ai-slop skill
(skills/no-ai-slop/SKILL.md), covering AI-slop patterns TruthCV's existing
anti-tell rules do not: the portability test, show-don't-tell, weasel
attribution, fake-strong verbs, synonym cycling, vague-scale words standing
in for a number, negative listing, and rhetorical setups. Style only; no
facts.
"""

from __future__ import annotations

from .conventions import CvConventions, DEFAULT_CONVENTIONS, DEFAULT_VOCABULARY

CV_STYLE = (
    " STYLE (phrasing and ordering only, add no facts): write to express, not "
    "impress: specific and fact-based, never flowery, no narrative prose, no "
    "slang and no ad-hoc or invented abbreviations, though established industry "
    "acronyms are fine when accompanied by their spelled-out form. Use active "
    "voice and strong action verbs (Led, "
    "Built, Designed, Engineered, Analyzed, Implemented, Optimized, Streamlined, "
    "Improved, Increased, Shipped, Owned); no personal pronouns; never start a line "
    "with a date. Shape each bullet as action -> contribution/scope -> "
    "impact/result, demonstrating outcomes rather than duties, but include a "
    "number or result ONLY if it is present in the referenced fact. Order the "
    "chosen experiences and bullets by relevance to the posting so the 3-4 most "
    "notable, role-relevant items stand out first; within equal relevance keep "
    "reverse chronological order (most recent first). Keep phrasing consistent "
    "and easy to scan for both human readers and ATS."
)

LETTER_STYLE = (
    " STYLE (phrasing only, add no facts): keep the letter to one page. Address a "
    "specific named recipient when one is known, otherwise use a role-appropriate "
    "greeting. Tailor to this specific organization and posting: reference the skills "
    "and requirements it names and draw explicit connections to the candidate's real "
    "experience. Write in natural first person and vary sentence rhythm; open with a "
    "hook that earns attention, never a template like 'I am writing to apply for'. "
    "Between the factual claims, write with genuine voice and specific interest in "
    "this role (the connective narrative is where the letter comes alive), but keep "
    "every concrete example anchored to a fact from the candidate's truth. The "
    "candidate's own name is printed in the letterhead above the body, so NEVER write "
    "the candidate's name in the letter text: do not name the candidate in the opening "
    "and do not add a signature or sign-off line with the candidate's name at the end. "
    "Structure: an opening that names the role and gives a reason to read on, then 1-2 "
    "body paragraphs of concrete supporting examples drawn ONLY from the facts, then a "
    "brief, forward-looking close."
)


_ANTI_SLOP_BANS = (
    " Additional AI-slop guardrails (style only, add no facts), distilled from "
    "the no-ai-slop skill: apply the portability test to every sentence - if it "
    "could move unchanged to another person, company, or product, cut it or "
    "replace it with a specific fact already in the truth. Show, don't tell: "
    "never label a point as important, notable, key, or worth noting, let the "
    "fact carry the weight. Do not use weasel attribution such as "
    "industry-leading, widely regarded as, world-class, or experts agree. "
    "Prefer a concrete, direct verb over an abstraction (write 'tracks "
    "sponsors, drafts, and due dates' rather than 'serves as a centralized hub "
    "for sponsor management'). Do not rotate synonyms for the same thing "
    "across sentences; repeat the clear word instead. Do not use vague-scale "
    "words such as significantly, substantially, various, or numerous, or 'a "
    "wide range of' in place of a number, unless that number is present in "
    "the referenced fact. Do not use negative listing ('not a X, not a Y, a "
    "Z') and do not use rhetorical setups."
)


def cv_anti_slop() -> str:
    """Render the CV-specific AI-slop bans, distilled from the no-ai-slop skill.

    Independent of, and additive to, ``cv_style``: covers patterns TruthCV's
    existing ``_CV_ANTI_TELL_RULES`` do not (portability, show-don't-tell,
    weasel attribution, fake-strong verbs, synonym cycling, vague-scale
    words, negative listing, rhetorical setups), plus a CV-only ban on
    dramatic bullet fragmentation. Style only; adds no facts.
    """
    return (
        _ANTI_SLOP_BANS
        + " Keep each bullet a single complete statement; do not fragment a "
        "bullet into short dramatic clauses."
    )


def letter_anti_slop() -> str:
    """Render the cover-letter-specific AI-slop bans, distilled from the
    no-ai-slop skill.

    Independent of, and additive to, ``letter_style``: covers patterns
    TruthCV's existing ``_ANTI_TELL_RULES`` do not (portability,
    show-don't-tell, weasel attribution, fake-strong verbs, synonym
    cycling, vague-scale words, negative listing, rhetorical setups), plus
    letter-only bans on summary-recap endings, fake-profound closers, and
    hollow adverbs. Style only; adds no facts.
    """
    return (
        _ANTI_SLOP_BANS
        + " Do not end with a summary-recap paragraph (In conclusion, "
        "Ultimately, Overall, or a final paragraph that restates the "
        "letter); end on the last concrete point or a plain next step. Do "
        "not close with a fake-profound metaphor or aphorism. Avoid hollow "
        "adverbs in the letter: successfully, effectively, efficiently, "
        "strategically, proactively."
    )


def _pronoun_clause(conventions: CvConventions) -> str:
    return (
        "personal pronouns are allowed"
        if conventions.allow_pronouns
        else "no personal pronouns"
    )


def _ordering_clause(conventions: CvConventions) -> str:
    if conventions.ordering == "functional":
        return "order sections by relevance to the posting"
    return "within equal relevance keep reverse chronological order (most recent first)"


def cv_style(conventions: CvConventions = DEFAULT_CONVENTIONS) -> str:
    """Render the CV style fragment from the supplied conventions.

    With the default conventions this is byte-identical to the historical
    ``CV_STYLE`` constant.
    """
    return (
        " STYLE (phrasing and ordering only, add no facts): write to express, not "
        "impress: specific and fact-based, never flowery, no narrative prose, no "
        "slang and no ad-hoc or invented abbreviations, though established industry "
        "acronyms are fine when accompanied by their spelled-out form. Use active "
        "voice and strong action verbs ("
        + DEFAULT_VOCABULARY.style_action_verbs
        + "); "
        + _pronoun_clause(conventions)
        + "; never start a line with a date. Shape each bullet as action -> "
        "contribution/scope -> impact/result, demonstrating outcomes rather than "
        "duties, but include a number or result ONLY if it is present in the "
        "referenced fact. Order the chosen experiences and bullets by relevance "
        "to the posting so the "
        + conventions.prominent_items
        + " most notable, role-relevant items stand out first; "
        + _ordering_clause(conventions)
        + ". Keep phrasing consistent and easy to scan for both human readers "
        "and ATS."
    )


def letter_style(conventions: CvConventions = DEFAULT_CONVENTIONS) -> str:
    """Render the cover-letter style fragment from the supplied conventions.

    With the default conventions this is byte-identical to the historical
    ``LETTER_STYLE`` constant.
    """
    return (
        " STYLE (phrasing only, add no facts): keep the letter to "
        + conventions.page_target
        + ". Address a specific named recipient when one is known, otherwise use "
        "a role-appropriate greeting. Tailor to this specific organization and "
        "posting: reference the skills and requirements it names and draw explicit "
        "connections to the candidate's real experience. Write in natural first "
        "person and vary sentence rhythm; open with a hook that earns attention, "
        "never a template like 'I am writing to apply for'. Between the factual "
        "claims, write with genuine voice and specific interest in this role (the "
        "connective narrative is where the letter comes alive), but keep every "
        "concrete example anchored to a fact from the candidate's truth. The "
        "candidate's own name is printed in the letterhead above the body, so "
        "NEVER write the candidate's name in the letter text: do not name the "
        "candidate in the opening and do not add a signature or sign-off line "
        "with the candidate's name at the end. Structure: an opening that names "
        "the role and gives a reason to read on, then 1-2 body paragraphs of "
        "concrete supporting examples drawn ONLY from the facts, then a brief, "
        "forward-looking close."
    )
