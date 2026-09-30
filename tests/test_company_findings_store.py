"""Tests for companyresearch.store: append-only writes and contradictions."""

from __future__ import annotations

import json

import pytest

from companyresearch import store


def test_load_all_missing_file_returns_empty(data_dir):
    assert store.load_all() == []


def test_load_all_malformed_json_returns_empty(data_dir):
    store.findings_path().parent.mkdir(parents=True, exist_ok=True)
    store.findings_path().write_text("{not valid json", encoding="utf-8")
    assert store.load_all() == []


def test_load_all_non_list_payload_returns_empty(data_dir):
    store.findings_path().parent.mkdir(parents=True, exist_ok=True)
    store.findings_path().write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert store.load_all() == []


def test_record_appends_and_never_mutates(data_dir):
    first = store.record(
        "Acme Co", "employer_rating", "4.5", "https://a.example/x", "press", "2024-01-01", "agent"
    )
    store.record(
        "Acme Co", "employer_rating", "3.0", "https://b.example/y", "review_site", "2024-02-01", "agent"
    )
    assert len(store.load_all()) == 2
    reloaded_first = store.get(first.id)
    assert reloaded_first.value == "4.5"
    assert reloaded_first.source_url == "https://a.example/x"
    assert reloaded_first.as_of == "2024-01-01"


def test_second_finding_contradicts_first_not_reverse(data_dir):
    first = store.record(
        "Acme Co", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent"
    )
    second = store.record(
        "Acme Co", "employer_rating", "3.0", "https://b.example/y", "review_site", "", "agent"
    )
    assert second.contradicts == [first.id]
    assert first.contradicts == []


def test_same_value_produces_no_contradiction(data_dir):
    store.record("Acme Co", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent")
    second = store.record(
        "Acme Co", "employer_rating", "4.5", "https://b.example/y", "review_site", "", "agent"
    )
    assert second.contradicts == []
    assert store.open_contradictions("Acme Co") == []


def test_uncited_finding_neither_contradicts_nor_is_contradicted(data_dir):
    store.record("Acme Co", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent")
    uncited = store.record(
        "Acme Co", "employer_rating", "unknown", "", "unattributed", "", "import"
    )
    assert uncited.contradicts == []
    # Recording another cited finding afterwards should not pick up the
    # uncited one as a contradiction partner either.
    third = store.record(
        "Acme Co", "employer_rating", "2.0", "https://c.example/z", "press", "", "agent"
    )
    assert uncited.id not in third.contradicts


def test_rejected_finding_drops_out_of_contradictions_but_stays_in_for_company(data_dir):
    first = store.record(
        "Acme Co", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent"
    )
    store.record(
        "Acme Co", "employer_rating", "3.0", "https://b.example/y", "review_site", "", "agent"
    )
    store.resolve(first.id, "rejected")
    assert store.open_contradictions("Acme Co") == []
    ids = {f.id for f in store.for_company("Acme Co")}
    assert first.id in ids

    later = store.record(
        "Acme Co", "employer_rating", "9.9", "https://d.example/w", "press", "", "agent"
    )
    assert first.id not in later.contradicts


def test_open_contradictions_clean_company_returns_empty(data_dir):
    store.record("Acme Co", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent")
    assert store.open_contradictions("Acme Co") == []


def test_open_contradictions_orders_strongest_source_first(data_dir):
    store.record(
        "Acme Co", "employer_rating", "3.0", "https://b.example/y", "review_site", "", "agent"
    )
    store.record(
        "Acme Co", "employer_rating", "4.5", "https://a.example/x", "company_statement", "", "agent"
    )
    groups = store.open_contradictions("Acme Co")
    assert len(groups) == 1
    findings = groups[0]["findings"]
    assert findings[0].source_class == "company_statement"
    assert findings[1].source_class == "review_site"


def test_resolve_unknown_id_returns_none(data_dir):
    assert store.resolve("nope", "accepted") is None


def test_resolve_unknown_resolution_raises(data_dir):
    finding = store.record(
        "Acme Co", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent"
    )
    with pytest.raises(ValueError):
        store.resolve(finding.id, "maybe")


def test_key_normalization_matches_variants(data_dir):
    store.record("Acme Co.", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent")
    matches = store.for_company("  acme co.  ")
    assert len(matches) == 1


def test_key_matches_across_legal_entity_suffixes(data_dir):
    """Findings for one employer are not split by a legal-entity suffix.

    The company key delegates to the shared company_identity_key, so
    research recorded against "RobCo GmbH" is found under "RobCo" too.
    """
    store.record("RobCo GmbH", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent")
    store.record("RobCo", "employer_rating", "4.5", "https://b.example/y", "press", "", "agent")

    assert len(store.for_company("RobCo")) == 2
    assert len(store.for_company("RobCo GmbH")) == 2


def test_contradictions_detected_across_legal_entity_suffixes(data_dir):
    """A contradicting claim under a suffix variant is still a contradiction."""
    store.record("RobCo GmbH", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent")
    store.record("RobCo", "employer_rating", "2.0", "https://b.example/y", "review_site", "", "agent")

    assert len(store.open_contradictions("RobCo")) == 1


def test_record_invalid_company_stores_nothing(data_dir):
    with pytest.raises(ValueError):
        store.record("n/a", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent")
    assert store.load_all() == []


def _rec(company="Acme Co", value="4.5", claim="employer_rating", **kw):
    return store.record(
        company, claim, value, "https://a.example/x", "press", "", "agent", **kw
    )


def test_record_other_requires_label(data_dir):
    with pytest.raises(ValueError, match="claim_label"):
        _rec(claim="other")
    assert _rec(claim="other", claim_label="Funding").claim_label == "Funding"


def test_record_rejects_claim_outside_enum(data_dir):
    with pytest.raises(ValueError, match="Unknown claim"):
        _rec(claim="glassdoor")
    assert store.load_all() == []


def test_supersede_validation_errors(data_dir):
    first = _rec()
    with pytest.raises(ValueError, match="unknown"):
        _rec(supersedes="nope")
    with pytest.raises(ValueError, match="different company"):
        _rec(company="Other Co", supersedes=first.id)
    with pytest.raises(ValueError, match="different claim"):
        _rec(claim="employment_entity", supersedes=first.id)
    _rec(value="5.0", supersedes=first.id)
    with pytest.raises(ValueError, match="already superseded"):
        _rec(value="1.0", supersedes=first.id)
    assert len(store.load_all()) == 2


def test_superseding_finding_does_not_contradict_target(data_dir):
    first = _rec()
    second = _rec(value="3.0", supersedes=first.id)
    assert second.contradicts == []
    assert store.open_contradictions("Acme Co") == []
    assert store.superseded_ids(store.load_all()) == {first.id}


def test_chained_supersede_does_not_resurrect_contradiction(data_dir):
    a = _rec()
    b = _rec(value="3.0", supersedes=a.id)
    c = _rec(value="2.0", supersedes=b.id)
    assert c.contradicts == []
    assert store.open_contradictions("Acme Co") == []


def test_other_claims_with_different_labels_do_not_contradict(data_dir):
    _rec(claim="other", claim_label="Funding stage", value="Series B")
    second = _rec(claim="other", claim_label="Headquarters", value="Berlin")
    assert second.contradicts == []
    assert store.open_contradictions("Acme Co") == []


def test_other_claims_same_label_case_insensitive_contradict(data_dir):
    first = _rec(claim="other", claim_label="Funding stage", value="Series B")
    second = _rec(claim="other", claim_label=" funding STAGE ", value="Series C")
    assert second.contradicts == [first.id]
    assert len(store.open_contradictions("Acme Co")) == 1


def test_supersede_other_with_different_label_raises(data_dir):
    first = _rec(claim="other", claim_label="Funding stage", value="Series B")
    with pytest.raises(ValueError, match="different claim"):
        _rec(claim="other", claim_label="Headquarters", value="Berlin", supersedes=first.id)


def test_group_clears_once_one_side_superseded(data_dir):
    first = _rec()
    _rec(value="3.0")
    assert len(store.open_contradictions("Acme Co")) == 1
    _rec(value="3.0", supersedes=first.id)
    assert store.open_contradictions("Acme Co") == []


def test_all_open_contradictions_matches_per_company_concatenation(data_dir):
    """all_open_contradictions() equals concatenation of per-company groups.

    Companies are ordered by earliest observed_at across their findings,
    matching the order they'd naturally appear when the whole dataset is
    read once, so this test records them out of alphabetical order.
    """
    store.record(
        "Beta Inc", "employer_rating", "3.0", "https://b.example/y", "review_site", "", "agent"
    )
    store.record(
        "Beta Inc", "employer_rating", "4.5", "https://a.example/x", "company_statement", "", "agent"
    )
    store.record(
        "Acme Co", "employer_rating", "1.0", "https://c.example/z", "review_site", "", "agent"
    )
    store.record(
        "Acme Co", "employer_rating", "2.0", "https://d.example/w", "company_statement", "", "agent"
    )

    combined = store.all_open_contradictions()
    expected = store.open_contradictions("Beta Inc") + store.open_contradictions("Acme Co")
    assert combined == expected
