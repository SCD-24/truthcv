"""Shared CV / cover-letter STYLE guidance injected into generation prompts.

Distilled from docs/reference/cv-style-guidelines.md. This is *style only* —
phrasing, structure, tone, action verbs. It contains NO facts and is NEVER a
source of content: the truthfulness rules in each prompt and the guardrail still
bind. These lines only shape how the user's own verified facts are phrased.
"""

CV_STYLE = (
    " STYLE (phrasing only, add no facts): use active voice and strong action "
    "verbs (Led, Built, Designed, Analyzed, Implemented, Improved, Increased, "
    "Streamlined, Spearheaded); no personal pronouns; be specific not flowery; "
    "shape each line as action -> contribution/scope -> result, but only include "
    "a number or outcome if it is present in the referenced fact; never start a "
    "line with a date."
)

LETTER_STYLE = (
    " STYLE (phrasing only, add no facts): concise and factual, under one page; "
    "tailor to this specific posting by connecting the candidate's real "
    "experience to its stated needs; use action words; avoid flowery language; "
    "do not overuse 'I'; open with who the candidate is and the role, then 1-2 "
    "body paragraphs of concrete supporting examples drawn ONLY from the facts, "
    "then a brief close."
)
