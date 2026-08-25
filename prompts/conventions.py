"""Configurable CV conventions and domain vocabulary for the prompt store.

TruthCV ships with no industry, country, or career stage baked in: everything
that used to be a fixed literal about *how a CV is written* (bullet counts,
ordering, page targets) or *what a profession's screenable vocabulary looks
like* (keyword scope, skill categories, action verbs) lives here as a value
object with today's behaviour as its defaults. Callers render prompt fragments
from these objects; supplying an alternative changes only those fragments.

The defaults exist so an operator who configures nothing gets byte-for-byte
the prompts this project has always produced — with one deliberate exception:
the ``acronym_policy`` and ``phrase_repetition_policy`` fields on
``DomainVocabulary`` are new, and their non-empty defaults intentionally CHANGE
the default prompt output because they did not exist before. An operator who
wants the old byte-for-byte prompts back can construct
``DomainVocabulary(acronym_policy="", phrase_repetition_policy="")`` to blank
them out.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CvConventions:
    """How the generated documents are shaped: structure, length, voice."""

    # Experience bullets per role in the tailored CV.
    bullets_min: int = 2
    bullets_max: int = 6
    # Whether the generated prose may use personal pronouns ("I", "we").
    allow_pronouns: bool = False
    # Section/bullet ordering policy within a CV.
    ordering: str = "reverse_chronological"  # or "functional"
    # Length target for a document ("one page", "two pages", ...).
    page_target: str = "one page"
    # How many leading items should be the most notable, role-relevant ones.
    prominent_items: str = "3-4"
    # Paragraph budget for a generated cover letter.
    letter_paragraphs_min: int = 3
    letter_paragraphs_max: int = 5


@dataclass(frozen=True)
class DomainVocabulary:
    """The screenable vocabulary of the candidate's domain.

    The defaults describe software engineering because that is what this
    project's first operator searched for — not because the craft rules below
    are SE-specific. A nurse's or lawyer's profile supplies its own profile so
    their screenable skills match the extraction and grouping rules.

    The ``acronym_policy`` and ``phrase_repetition_policy`` fields belong to the
    same screenable-vocabulary concern: they govern ATS-matching *phrasing* (how
    a supported fact should be worded so a keyword scanner registers it), not the
    facts themselves.
    """

    # What counts as a screenable keyword, rendered into the extraction prompt.
    keyword_scope: str = (
        "technologies, tools, programming languages, frameworks, platforms, "
        "methodologies, and hard requirements (e.g. specific certifications "
        "or years with a named tool)"
    )
    # Skill groupings the tailoring step may bucket skills into.
    skill_categories: str = (
        "languages, frameworks, cloud platforms, databases, tools, "
        "analytics, certifications"
    )
    # Action verbs the CV bullets are encouraged to open with.
    action_verbs: str = (
        "built, led, shipped, owned, cut, raised, designed, implemented, "
        "streamlined"
    )
    # Capitalised variant injected by the shared CV style fragment.
    style_action_verbs: str = (
        "Led, Built, Designed, Engineered, Analyzed, Implemented, Optimized, "
        "Streamlined, Improved, Increased, Shipped, Owned"
    )
    # Plain-verb preference listed by the anti-'AI tell' rules.
    plain_action_verbs: str = "built, led, shipped, owned, cut, raised, fixed"
    # Legitimate-support examples shown to the inference step.
    inference_examples: str = (
        "a bullet describing moving or converting data between systems supports "
        "'ETL' and 'Data transformation'; building checks on input data supports "
        "'Data validation'; tuning a system for speed supports 'Performance "
        "optimization'"
    )
    # Carry both an acronym and its expansion when the facts support both.
    acronym_policy: str = (
        "When an established industry acronym and its full spelled-out form are both "
        "supported by the candidate's own facts, write the expansion once followed by "
        "the acronym in parentheses (e.g. 'Continuous Integration and Continuous "
        "Delivery (CI/CD)') so an applicant-tracking system matching either form as a "
        "literal phrase can find it, since ATS keyword taxonomies treat an acronym and "
        "its expansion as unrelated entries."
    )
    # Never elide a repeated head noun across a conjunction.
    phrase_repetition_policy: str = (
        "Never share a head noun across a conjunction: write 'unit tests and "
        "integration tests', not 'unit and integration tests', because a scanner "
        "that matches contiguous phrases cannot see the elided form and the shortened "
        "phrasing will not register as a keyword match."
    )


DEFAULT_CONVENTIONS = CvConventions()
DEFAULT_VOCABULARY = DomainVocabulary()


_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def page_target_pages(conventions: CvConventions = DEFAULT_CONVENTIONS) -> int | None:
    """Parse ``conventions.page_target`` into a numeric page limit.

    Understands written number words ("one".."five") and digits (1-5),
    optionally followed by "page"/"pages" (e.g. "one page", "2 pages", "1").
    Returns None when the string can't be parsed this way (e.g. "as short
    as possible"), so callers can skip any page-count check rather than
    guess at the operator's intent.
    """
    text = conventions.page_target.strip().lower()
    first_word = text.split()[0] if text.split() else ""
    if first_word in _NUMBER_WORDS:
        return _NUMBER_WORDS[first_word]
    if first_word.isdigit():
        return int(first_word)
    return None
