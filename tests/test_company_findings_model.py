"""Tests for companyresearch.model: source ranking and validation rules."""

from __future__ import annotations

import pytest

from companyresearch.model import (
    CompanyFinding,
    SOURCE_CLASSES,
    source_rank,
    validate_finding,
)


def test_source_rank_orders_strongest_first():
    assert source_rank("audited_accounts") < source_rank("listed_bond_price")
    assert source_rank("listed_bond_price") < source_rank("press")


def test_source_rank_unknown_class_ranks_last():
    assert source_rank("made_up_class") == len(SOURCE_CLASSES)
    assert source_rank("press") < source_rank("made_up_class")


def test_validate_finding_rejects_bad_company_name():
    with pytest.raises(ValueError, match="company name"):
        validate_finding("n/a", "claim", "value", "https://x.example", "press", "agent")


def test_validate_finding_rejects_empty_claim():
    with pytest.raises(ValueError, match="claim is required"):
        validate_finding("Acme Co", "  ", "value", "https://x.example", "press", "agent")


def test_validate_finding_rejects_empty_value():
    with pytest.raises(ValueError, match="value is required"):
        validate_finding("Acme Co", "claim", "  ", "https://x.example", "press", "agent")


def test_validate_finding_rejects_unknown_source_class():
    with pytest.raises(ValueError, match="Unknown source_class"):
        validate_finding("Acme Co", "claim", "value", "https://x.example", "rumor", "agent")


def test_validate_finding_rejects_unknown_recorded_by():
    with pytest.raises(ValueError, match="Unknown recorded_by"):
        validate_finding("Acme Co", "claim", "value", "https://x.example", "press", "bot")


def test_validate_finding_rejects_agent_write_with_no_source_url():
    with pytest.raises(ValueError, match="source_url is required"):
        validate_finding("Acme Co", "claim", "value", "", "press", "agent")


def test_validate_finding_accepts_import_unattributed_with_no_url():
    validate_finding("Acme Co", "claim", "value", "", "unattributed", "import")


def test_from_dict_ignores_unknown_keys_and_defaults_missing():
    finding = CompanyFinding.from_dict({"id": "abc123", "bogus_key": "nope"})
    assert finding.id == "abc123"
    assert finding.company == ""
    assert finding.contradicts == []
    assert not hasattr(finding, "bogus_key")


def test_to_dict_from_dict_round_trip():
    original = CompanyFinding(
        id="f1",
        company="Acme Co",
        claim="employer_rating",
        value="4.5",
        source_url="https://x.example/page",
        source_class="press",
        as_of="2024-01-01",
        observed_at="2024-01-02T00:00:00+00:00",
        recorded_by="agent",
        note="found via press release",
        contradicts=["f0"],
        resolution="accepted",
        resolved_at="2024-01-03T00:00:00+00:00",
        resolution_note="confirmed by operator",
    )
    round_tripped = CompanyFinding.from_dict(original.to_dict())
    assert round_tripped == original
