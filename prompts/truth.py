"""Prompt served for the Truth Store: profile → structured truth extraction.

This system prompt only asks the provider to *group* verifiable facts by the
experience they belong to and to copy them verbatim — never to infer or add.
Nothing it returns is trusted until it flows through the store and, at render
time, the deterministic guardrail.
"""

from __future__ import annotations


def extract_system() -> str:
    """System prompt: extract verifiable facts from LinkedIn profile text, grouped
    by experience, copying everything verbatim (no inference)."""
    return (
        "You extract verifiable facts from a person's LinkedIn profile text and group "
        "them by the experience they belong to. Return ONLY facts literally present in "
        "the text — never infer, embellish, or add anything. "
        "For each job produce an experience with its role title, company, start and end "
        "(dates exactly as written; use an empty string if a date is absent, or 'Present' "
        "for a current role), and its responsibility/achievement lines as bullets — put "
        "each bullet with the job it appears under, never in a different job. "
        "Capture education as degree + school + start/end, and a flat list of skills. "
        "Also extract a top-level profile header, copying VERBATIM (no inference): the "
        "person's name, email, phone, location, any profile links (each as label + url), "
        "and — only if the text contains a headline or personal summary paragraph — a "
        "short summary of it. Leave any profile field an empty string (or the links an "
        "empty list) when the text does not state it. "
        "Do not duplicate bullets or skills."
    )
