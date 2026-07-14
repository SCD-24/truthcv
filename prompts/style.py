"""Shared CV / cover-letter STYLE guidance injected into generation prompts.

Distilled from docs/reference/cv-style-guidelines.md. This is *style only* —
phrasing, structure, tone, action verbs. It contains NO facts and is NEVER a
source of content: the truthfulness rules in each prompt and the guardrail still
bind. These lines only shape how the user's own verified facts are phrased.
"""

CV_STYLE = (
    " STYLE (phrasing and ordering only, add no facts): write to express, not "
    "impress: specific and fact-based, never flowery, no narrative prose, no "
    "abbreviations or slang. Use active voice and strong action verbs (Led, "
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
    "every concrete example anchored to a fact from the candidate's truth. Structure: "
    "an opening that names the candidate and the role and gives a reason to read on, "
    "then 1-2 body paragraphs of concrete supporting examples drawn ONLY from the "
    "facts, then a brief, forward-looking close."
)
