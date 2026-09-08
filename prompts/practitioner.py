"""Prompt text for the practitioner cover-letter fragments.

This module holds prose only. It defines the twenty-two seeded fragments
distilled from the practitioner cover-letter prompt (one ``voice``, one
``structure``, one ``opener``, and nineteen ``rules``) as module-level string
constants, and exposes them as ``PRACTITIONER_SPECS`` so
``prompts/fragments.py`` can turn each entry into a ``Fragment`` without
importing any prose of its own.

Every fragment stands alone and reads correctly when concatenated in any
order with the others, because ``prompts/assemble.py`` joins fragment texts
with a single space.

Hard character rules, asserted on the assembled prompt by
``tests/test_prompts_style.py``: no em dashes, no en dashes, no curly quotes.
Use straight quotes only.
"""

from __future__ import annotations


_VOICE_PRACTITIONER = (
    "Voice: direct, conversational, and technically literate. Thoughtful, "
    "confident, and self-aware, slightly informal where that fits, and "
    "professional without sounding corporate. Write as an experienced "
    "practitioner explaining their work to another professional. Prefer "
    "openings such as \"I'm interested in this role because\", \"The part of "
    "this problem that caught my attention is\", \"I've spent much of my "
    "career\", \"I want to be transparent that\", or \"What appeals to me "
    "most is\", rather than \"I am thrilled to submit my application\", \"I "
    "am excited about the opportunity\", \"I believe I would be an "
    "exceptional fit\", or \"I am passionate about\"."
)

_STRUCTURE_NARRATIVE_ARC = (
    "Structure: build a narrative rather than a list of qualifications "
    "disguised as paragraphs. The company has a problem, the candidate has "
    "met similar problems, here is what they actually built, here is what "
    "they learned, and here is why this role is interesting. Default order: "
    "why the problem caught their attention; the most relevant professional "
    "experience; a deeper connection to the company's actual problem; "
    "relevant technical depth or adjacent experience; relevant personal or "
    "independent projects; an honest discussion of a gap where that is "
    "useful; why this team is interesting; and a natural close. Do not force "
    "this order when another one produces a better letter. Not every "
    "paragraph needs to introduce a new technology. Target roughly 2,500 to "
    "4,000 characters unless a limit is specified."
)

_OPENER_PROBLEM_FIRST = (
    "Open with the actual reason the role is interesting, connecting the "
    "candidate to the engineering or business problem behind it. Never open "
    "with \"I am writing to express my interest\", \"I am thrilled to "
    "apply\", or \"I am excited to submit my application\". The opening must "
    "feel specific to this company."
)

_RULES_TEXT: dict[str, str] = {
    "rules-truth-store-authority": (
        "The truth store is the sole factual authority for employment "
        "history, responsibilities, technologies, projects, achievements, "
        "metrics, education, location, work authorization, personal "
        "projects, dates, and stored motivations. Do not invent, infer, "
        "embellish, or assume anything it does not support. If it does not "
        "establish experience with a technology, do not claim it."
    ),
    "rules-tailor-from-posting": (
        "Tailor every letter to this specific posting. Read the "
        "application's posting text closely and pair it with the details in "
        "the candidate's truth file. The letter must be recognisably about "
        "this role, not a reusable template."
    ),
    "rules-select-dont-dump": (
        "Retrieval returns more than is needed, so filter it. Choose the "
        "facts that best support the narrative for this role. Do not dump "
        "retrieved facts and do not try to mention every relevant fact. "
        "Relevance and authenticity beat completeness. Do not optimise for "
        "keyword coverage."
    ),
    "rules-understand-the-job": (
        "Before writing, work out internally what the company is trying to "
        "accomplish, what problems this person would solve, which "
        "capabilities genuinely matter, which of the candidate's experiences "
        "demonstrate them, which give supporting evidence, where the real "
        "gaps are, and what could honestly interest the candidate."
    ),
    "rules-underlying-connection": (
        "Do not map job-description keywords to candidate keywords. Find the "
        "underlying connection: explain why the problems the candidate has "
        "already solved bear on the problem described in the posting."
    ),
    "rules-naturalness": (
        "Do not over-polish. Natural phrasing beats rhetorical symmetry. "
        "Allow contractions, varied sentence lengths, occasional informal "
        "phrasing, small personal observations, technically specific asides, "
        "honest qualifications, and opinions about engineering tradeoffs. Do "
        "not give every paragraph the same shape. Do not make every sentence "
        "impressive; an ordinary true sentence beats an impressive generic "
        "one."
    ),
    "rules-learn-voice-from-samples": (
        "When writing samples are available, learn the candidate's sentence "
        "rhythm, formality, vocabulary, humour, how they explain technical "
        "details, how they express opinions, and how they describe "
        "limitations. Learn the underlying voice rather than copying "
        "phrases. With no samples, use a natural, direct, professional "
        "engineering voice rather than a conventional cover-letter voice. Do "
        "not manufacture personality."
    ),
    "rules-technical-specificity": (
        "Prefer concrete evidence over claims about ability. Instead of "
        "\"extensive experience building scalable platforms\", describe the "
        "actual system, the technologies, the scale, the ownership, the "
        "constraints, the engineering decisions, the operational "
        "responsibilities, and the measurable outcomes the truth store "
        "supports."
    ),
    "rules-no-invented-metrics": (
        "Do not invent metrics, exaggerate scale, or turn ordinary work into "
        "extraordinary achievement."
    ),
    "rules-honest-gaps": (
        "When the posting asks for something the candidate lacks and it "
        "matters, do not hide it and do not pass adjacent experience off as "
        "direct. Say what they have worked with, what underlying problem "
        "overlaps, and why the missing piece is a technology gap rather than "
        "a new domain. Do not turn every gap into an apology, and do not "
        "raise gaps that do not matter."
    ),
    "rules-personal-projects": (
        "Use personal projects when they give real evidence for the role, "
        "not by default. Include one only if it shows a relevant capability, "
        "useful technical curiosity, ownership, the candidate's engineering "
        "approach, or why this type of work interests them."
    ),
    "rules-entrepreneurial-experience": (
        "Treat entrepreneurial or independent work supported by the truth "
        "store as real engineering experience: evidence of end-to-end "
        "ownership, product thinking, pragmatism, operating systems, "
        "understanding users, balancing quality against delivery, and "
        "independent architectural decisions. Do not frame it as startup "
        "success; the value is what was built, operated, learned, or decided."
    ),
    "rules-company-specific-reasoning": (
        "Do not echo the company's own language back at it. If the posting "
        "says \"build scalable, reusable data infrastructure\", do not write "
        "that the candidate is excited to build scalable, reusable data "
        "infrastructure. Explain what that means in practical engineering "
        "terms and why the problem is interesting. The candidate should read "
        "as someone who thought about the problem, not someone who extracted "
        "keywords."
    ),
    "rules-personal-details": (
        "Include personal details such as location, work authorization, the "
        "reason for a transition, independent projects, or hobbies that "
        "involve building things only when they are relevant or add genuine "
        "personality. Never add personal information to pad length."
    ),
    "rules-length-discipline": (
        "Default to roughly 2,500 to 4,000 characters. Obey any specified "
        "character limit strictly. Do not pad. If there is not enough "
        "relevant material, write a shorter letter."
    ),
    "rules-no-em-dashes": (
        "Never use em dashes or en dashes. Use commas, parentheses, "
        "semicolons, or two sentences. Use straight quotes only, never curly "
        "quotes."
    ),
    "rules-avoid-corporate-language": (
        "Avoid excessive buzzwords, adjectives, corporate and motivational "
        "language, claims of excellence, repetition, and job-description "
        "terminology. Avoid \"unique combination of skills\", \"proven track "
        "record\", \"passionate about\", \"exciting opportunity\", \"dynamic "
        "environment\", \"cutting-edge\", \"leverage my expertise\", \"drive "
        "innovation\", and \"make a meaningful impact\", unless one "
        "genuinely fits the candidate's natural voice and is needed. Never "
        "use language merely because it sounds like a cover letter."
    ),
    "rules-final-self-review": (
        "Before returning the letter, silently check that it sounds like a "
        "real person and like this candidate; that it shows understanding of "
        "the actual job; that there is a clear reason this role interests "
        "them; that every major claim is supported by the truth store; that "
        "the technical details are concrete; that information was selected "
        "rather than dumped; that nothing is exaggerated; that important "
        "gaps are handled honestly; that there is some personality; that "
        "generic AI and corporate language is absent; that the job "
        "description is not parroted; and that the candidate could "
        "realistically send it. Rewrite before returning if any of that "
        "fails."
    ),
    "rules-letter-body-discipline": (
        "The letter body must be finished, sendable prose: no analysis, no "
        "explanation of writing choices, no list of matched qualifications, "
        "no citations, source ids, or retrieval metadata, and no references "
        "to the truth store as a system. The candidate's own name is printed "
        "in the letterhead above the body and a sign-off is appended after "
        "it, so NEVER write the candidate's name in the letter text: do not "
        "name the candidate in the opening, and do not end with a sign-off "
        "or signature line."
    ),
}

_RULES_TITLES: dict[str, str] = {
    "rules-truth-store-authority": "Truth store is the only authority",
    "rules-tailor-from-posting": "Tailor from the posting",
    "rules-select-dont-dump": "Select facts, do not dump them",
    "rules-understand-the-job": "Understand the job first",
    "rules-underlying-connection": "Underlying connection, not keywords",
    "rules-naturalness": "Naturalness over polish",
    "rules-learn-voice-from-samples": "Learn the voice from samples",
    "rules-technical-specificity": "Technical specificity",
    "rules-no-invented-metrics": "No invented metrics",
    "rules-honest-gaps": "Handle gaps honestly",
    "rules-personal-projects": "Personal projects as evidence",
    "rules-entrepreneurial-experience": "Entrepreneurial experience counts",
    "rules-company-specific-reasoning": "Company-specific reasoning",
    "rules-personal-details": "Personal details only when relevant",
    "rules-length-discipline": "Length discipline",
    "rules-no-em-dashes": "No em dashes or curly quotes",
    "rules-avoid-corporate-language": "Avoid corporate language",
    "rules-final-self-review": "Final self-review",
    "rules-letter-body-discipline": "Letter body discipline",
}

_RULE_IDS: tuple[str, ...] = (
    "rules-truth-store-authority",
    "rules-tailor-from-posting",
    "rules-select-dont-dump",
    "rules-understand-the-job",
    "rules-underlying-connection",
    "rules-naturalness",
    "rules-learn-voice-from-samples",
    "rules-technical-specificity",
    "rules-no-invented-metrics",
    "rules-honest-gaps",
    "rules-personal-projects",
    "rules-entrepreneurial-experience",
    "rules-company-specific-reasoning",
    "rules-personal-details",
    "rules-length-discipline",
    "rules-no-em-dashes",
    "rules-avoid-corporate-language",
    "rules-final-self-review",
    "rules-letter-body-discipline",
)
"""The nineteen practitioner ``rules`` fragment ids, in assembly order."""


def _rules_specs() -> list[dict[str, str]]:
    """Build one spec dict per practitioner ``rules`` fragment, in order."""
    return [
        {
            "id": rule_id,
            "slot": "rules",
            "title": _RULES_TITLES[rule_id],
            "text": _RULES_TEXT[rule_id],
        }
        for rule_id in _RULE_IDS
    ]


PRACTITIONER_SPECS: list[dict[str, str]] = [
    {
        "id": "voice-practitioner",
        "slot": "voice",
        "title": "Practitioner",
        "text": _VOICE_PRACTITIONER,
    },
    {
        "id": "structure-narrative-arc",
        "slot": "structure",
        "title": "Narrative arc",
        "text": _STRUCTURE_NARRATIVE_ARC,
    },
    {
        "id": "opener-problem-first",
        "slot": "opener",
        "title": "Problem-first opener",
        "text": _OPENER_PROBLEM_FIRST,
    },
    *_rules_specs(),
]
"""The twenty-two practitioner fragment specs: one voice, one structure, one
opener, and nineteen rules, each atomic and independently swappable."""

PRACTITIONER_FRAGMENT_IDS: tuple[str, ...] = tuple(spec["id"] for spec in PRACTITIONER_SPECS)
"""Every practitioner fragment id, in the order the preset selects them."""
