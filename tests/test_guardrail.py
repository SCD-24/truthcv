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


# --- Operator synonym map (data/vocabulary/synonyms.txt) traceability -------
#
# A term attested in one accepted form is traceable in any of its registered
# equivalent forms. The map only ever WIDENS a scope's own allowed set — it never
# grants blanket permission across scopes or for forms nothing in scope attests.


def test_acronym_in_truth_expansion_in_draft_passes(data_dir):
    """Truth attests the acronym; a draft using the registered expansion passes."""
    import vocabulary.synonyms as vs

    vocab = data_dir / "vocabulary"
    vocab.mkdir()
    (vocab / "synonyms.txt").write_text(
        "CI/CD = Continuous Integration and Continuous Delivery\n", encoding="utf-8"
    )
    vs._synonyms_cache = None  # reset the per-data_dir cache after writing the file

    result = validate(
        [
            Scope(
                id="exp-1",
                texts=["Continuous Integration and Continuous Delivery"],
                allowed=["CI/CD"],
            )
        ]
    )
    assert result.ok, result.unverifiable
    assert result.unverifiable == []

    vs._synonyms_cache = None


def test_expansion_in_truth_acronym_in_draft_passes(data_dir):
    """Reverse direction: truth attests the expansion; a draft acronym passes."""
    import vocabulary.synonyms as vs

    vocab = data_dir / "vocabulary"
    vocab.mkdir()
    (vocab / "synonyms.txt").write_text(
        "CI/CD = Continuous Integration and Continuous Delivery\n", encoding="utf-8"
    )
    vs._synonyms_cache = None

    result = validate(
        [
            Scope(
                id="exp-1",
                texts=["CI/CD"],
                allowed=["Continuous Integration and Continuous Delivery"],
            )
        ]
    )
    assert result.ok, result.unverifiable
    assert result.unverifiable == []

    vs._synonyms_cache = None


def test_unattested_synonym_group_grants_no_permission(data_dir):
    """A group present in the file but attested by nothing in scope rescues nothing."""
    import vocabulary.synonyms as vs

    vocab = data_dir / "vocabulary"
    vocab.mkdir()
    # Neither "AWS" nor "Amazon Web Services" appears in this scope's truth.
    (vocab / "synonyms.txt").write_text(
        "AWS = Amazon Web Services\n", encoding="utf-8"
    )
    vs._synonyms_cache = None

    result = validate(
        [
            Scope(
                id="exp-1",
                texts=["Amazon Web Services"],
                allowed=["Built a payments API in Python"],
            )
        ]
    )
    assert not result.ok
    for tok in ("amazon", "web", "services"):
        assert tok in result.unverifiable

    vs._synonyms_cache = None


def test_synonym_expansion_is_per_scope(data_dir):
    """A form attested only in scope A does not unblock the phrase in scope B."""
    import vocabulary.synonyms as vs

    vocab = data_dir / "vocabulary"
    vocab.mkdir()
    (vocab / "synonyms.txt").write_text(
        "CI/CD = Continuous Integration and Continuous Delivery\n", encoding="utf-8"
    )
    vs._synonyms_cache = None

    scope_a = Scope(
        id="job-a",
        texts=["Continuous Integration and Continuous Delivery"],
        allowed=["CI/CD"],  # attests the acronym form
    )
    scope_b = Scope(
        id="job-b",
        texts=["Continuous Integration and Continuous Delivery"],
        allowed=["Python"],  # attests neither form
    )
    result = validate([scope_a, scope_b])

    assert not result.ok
    # Scope A resolves via its own attested acronym; scope B does not.
    assert not any(c.scope_id == "job-a" for c in result.blocked_claims)
    assert any(c.scope_id == "job-b" for c in result.blocked_claims)
    for tok in ("continuous", "integration", "delivery"):
        assert tok in result.unverifiable

    vs._synonyms_cache = None


def test_no_synonyms_file_leaves_verdicts_unchanged(data_dir):
    """Canary: with no synonyms file, verdicts match today's exact behaviour."""
    import vocabulary.synonyms as vs
    import guardrail.validate as gv

    # No data/vocabulary/synonyms.txt written on this fresh volume.
    vs._synonyms_cache = None
    gv._stopwords_cache = None

    passing = validate(
        [_scope("Senior Software Engineer at Acme Corp")],
        global_values=GLOBAL_SKILLS,
    )
    assert passing.ok, passing.unverifiable

    blocked = validate(
        [_scope("Built a payments API in Python and Kubernetes")],
        global_values=GLOBAL_SKILLS,
    )
    assert not blocked.ok
    assert "kubernetes" in blocked.unverifiable

    vs._synonyms_cache = None
    gv._stopwords_cache = None
