"""Guardrail truthfulness-invariant tests (pure, no provider).

Validation is per-scope: each draft `Scope` may only draw on its own `allowed`
truth values plus any global skill values. A token that is neither a stopword nor
traceable to its scope's allowed set is unverifiable — nothing fabricated passes.
"""

from __future__ import annotations

from guardrail import validate, Scope


# One experience's truth facts, expressed as the values that scope may draw on.
EXPERIENCE_ALLOWED = [
    "Senior Software Engineer",
    "Acme Corp",
    "Built a payments API in Python",
    "Shipped 3 microservices",
]
GLOBAL_SKILLS = ["Python"]


def _scope(*texts: str, allowed: list[str] | None = None) -> Scope:
    return Scope(id="exp-1", texts=list(texts), allowed=allowed or EXPERIENCE_ALLOWED)


def test_draft_built_only_from_truth_passes():
    result = validate(
        [
            _scope(
                "Senior Software Engineer at Acme Corp",
                "Delivered a payments API in Python",  # 'Delivered a' are stopwords
                "Shipped 3 microservices",
            )
        ],
        global_values=GLOBAL_SKILLS,
    )
    assert result.ok, result.unverifiable
    assert result.unverifiable == []


def test_fabricated_token_is_flagged():
    result = validate(
        [_scope("Built a payments API in Python and Kubernetes")],
        global_values=GLOBAL_SKILLS,
    )
    assert not result.ok
    assert "kubernetes" in result.unverifiable


def test_fabricated_metric_is_flagged():
    # A number not present in this scope's truth (inflated achievement) is caught.
    result = validate([_scope("Shipped 9 microservices")], global_values=GLOBAL_SKILLS)
    assert not result.ok
    assert "9" in result.unverifiable


def test_case_whitespace_punctuation_normalized():
    result = validate([_scope("  ACME   corp,  PYTHON!!  ")], global_values=GLOBAL_SKILLS)
    assert result.ok, result.unverifiable


def test_golden_invariant_only_truth_tokens_survive():
    # Any token in the draft that is neither a stopword nor a truth token is
    # reported — nothing fabricated can pass.
    result = validate(
        [_scope("Managed a team of 200 at Globex using Rust")],
        global_values=GLOBAL_SKILLS,
    )
    assert not result.ok
    for fabricated in ("200", "globex", "rust"):
        assert fabricated in result.unverifiable


def test_token_from_another_scope_is_unverifiable():
    # The per-experience invariant: a fact real in one job cannot attach to another.
    scopes = [
        Scope(id="job-a", texts=["Worked at Acme Corp"], allowed=["Acme Corp"]),
        Scope(id="job-b", texts=["Worked at Acme Corp"], allowed=["Globex Inc"]),
    ]
    result = validate(scopes, global_values=[])
    assert not result.ok
    assert "acme" in result.unverifiable
