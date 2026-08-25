"""Vocabulary layer invariants: synonym-file parsing and keyword matching.

These pin the operator-editable synonym store (vocabulary/synonyms.py) and the
token/phrase-aware matcher (vocabulary/match.py). Every test uses the data_dir
fixture so DATA_DIR is a tmp_path and the real ./data is never touched.
"""

from __future__ import annotations

import vocabulary.synonyms as vs
from vocabulary.match import (
    ABSENT,
    ALIAS_ONLY,
    EXACT,
    INTERLEAVED,
    match_keyword,
)
from vocabulary.synonyms import equivalent_forms, synonym_groups


def test_group_parsing_skips_comments_and_blanks(data_dir):
    """Comment and blank lines are ignored; real '=' groups still parse."""
    vocab_dir = data_dir / "vocabulary"
    vocab_dir.mkdir()
    (vocab_dir / "synonyms.txt").write_text(
        "# leading comment\n"
        "\n"
        "foo = bar\n"
        "\n"
        "# another comment\n"
        "baz = qux\n",
        encoding="utf-8",
    )
    vs._synonyms_cache = None  # reset the per-data_dir cache for this test

    assert equivalent_forms("foo") == frozenset({"bar"})
    assert equivalent_forms("baz") == frozenset({"qux"})
    assert len(synonym_groups()) == 2


def test_missing_file_yields_no_synonyms(data_dir):
    """No synonyms.txt means no groups and an empty equivalent_forms result."""
    vs._synonyms_cache = None  # reset so we don't read a stale cache

    assert synonym_groups() == ()
    assert equivalent_forms("anything") == frozenset()


def test_unreadable_file_degrades_to_empty(data_dir):
    """An OSError on read (synonyms.txt is a directory) degrades, not raises."""
    vocab_dir = data_dir / "vocabulary"
    vocab_dir.mkdir()
    # A directory where the file should be forces IsADirectoryError (an OSError
    # subclass) from read_text, exercising the degrade-to-empty path.
    (vocab_dir / "synonyms.txt").mkdir()
    vs._synonyms_cache = None  # reset the per-data_dir cache for this test

    assert synonym_groups() == ()
    assert equivalent_forms("foo") == frozenset()


def test_equivalent_forms_returns_whole_group_minus_self(data_dir):
    """A three-form group resolves each member to the other two, symmetrically."""
    vocab_dir = data_dir / "vocabulary"
    vocab_dir.mkdir()
    (vocab_dir / "synonyms.txt").write_text(
        "k8s = kubernetes = container orchestration\n", encoding="utf-8"
    )
    vs._synonyms_cache = None  # reset the per-data_dir cache for this test

    assert equivalent_forms("k8s") == frozenset({"kubernetes", "container orchestration"})
    assert equivalent_forms("KUBERNETES") == frozenset({"k8s", "container orchestration"})


def test_match_keyword_four_verdicts(data_dir):
    """All four verdicts are reachable with concrete text/keyword pairs."""
    vs._synonyms_cache = None  # no synonyms file: aliases come from the arg only

    assert match_keyword("Python", "I write Python code") == EXACT
    assert match_keyword("unit tests", "Wrote unit and integration tests") == INTERLEAVED
    assert match_keyword("k8s", "Ran kubernetes in prod", aliases=["kubernetes"]) == ALIAS_ONLY
    assert match_keyword("Rust", "I write Python code") == ABSENT


def test_go_django_false_positive_gone(data_dir):
    """'Go' must not match inside 'Django' — it is token-based, not substring."""
    vs._synonyms_cache = None  # reset so no stale synonyms leak in

    assert match_keyword("Go", "Built the backend in Django") == ABSENT


def test_unit_tests_interleaves(data_dir):
    """'unit tests' is covered by 'unit and integration tests' as interleaved."""
    vs._synonyms_cache = None  # reset so no stale synonyms leak in

    assert match_keyword("unit tests", "Wrote unit and integration tests") == INTERLEAVED


def test_acronym_expansion_from_disk_synonyms(data_dir):
    """A synonyms.txt expansion resolves an acronym to alias-only with no arg."""
    vocab_dir = data_dir / "vocabulary"
    vocab_dir.mkdir()
    (vocab_dir / "synonyms.txt").write_text(
        "CI/CD = Continuous Integration and Continuous Delivery\n", encoding="utf-8"
    )
    vs._synonyms_cache = None  # reset so the freshly-written file is read

    verdict = match_keyword(
        "CI/CD",
        "Owned the Continuous Integration and Continuous Delivery pipeline",
    )
    assert verdict == ALIAS_ONLY
