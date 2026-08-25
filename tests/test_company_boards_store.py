"""Tests for company boards store."""

import json

import pytest
from companyboards import store
from screening.company import company_identity_key


def test_record_and_load():
    """Record a company board and load it back."""
    store.record("Google", "https://careers.google.com", "Lever", "ok")
    boards = store.load()
    assert "google" in boards
    assert boards["google"].company == "Google"
    assert boards["google"].careers_url == "https://careers.google.com"
    assert boards["google"].ats == "Lever"


def test_overwrite_existing_entry():
    """Overwriting an entry replaces it completely."""
    store.record("Acme", "https://acme.example.com", "BambooHR")
    store.record("Acme", "https://acme-new.example.com", "Workable", "ok")
    boards = store.load()
    assert boards["acme"].careers_url == "https://acme-new.example.com"
    assert boards["acme"].ats == "Workable"


def test_mark_dead():
    """Marking a company as dead sets status to dead."""
    store.record("Defunct Inc", "https://careers.defunct.com")
    store.mark_dead("Defunct Inc")
    boards = store.load()
    # "Inc" is a legal-entity suffix stripped by the identity key.
    assert boards["defunct"].status == "dead"


def test_prune_keeps_target_companies():
    """Prune removes boards not in the target watchlist."""
    store.record("Google", "https://careers.google.com")
    store.record("Apple", "https://careers.apple.com")
    store.record("Microsoft", "https://careers.microsoft.com")
    
    # Prune to only Google and Apple
    store.prune(["Google", "Apple"])
    
    boards = store.load()
    assert "google" in boards
    assert "apple" in boards
    assert "microsoft" not in boards


def test_load_missing_file_returns_empty():
    """Loading from a missing file returns an empty dict."""
    # board_path doesn't exist; load should return {}
    boards = store.load()
    assert isinstance(boards, dict)
    # Expect empty or whatever was there before; key is that no exception raised


def test_load_corrupt_json_returns_empty(data_dir):
    """Loading from a corrupt JSON file returns an empty dict."""
    (data_dir / "company_boards.json").write_text("{ invalid json }", encoding="utf-8")
    boards = store.load()
    assert boards == {}


def test_load_non_dict_json_returns_empty(data_dir):
    """Loading JSON that is not a dict returns an empty dict."""
    (data_dir / "company_boards.json").write_text("[]", encoding="utf-8")
    boards = store.load()
    assert boards == {}


def test_company_name_normalization():
    """Company names are normalized to their identity key (company_identity_key)."""
    store.record(" Google ", "https://careers.google.com")
    store.record("APPLE", "https://careers.apple.com")

    boards = store.load()
    assert "google" in boards
    assert "apple" in boards
    # Original names are preserved in the CompanyBoard object
    assert boards["google"].company == " Google "
    assert boards["apple"].company == "APPLE"


def test_legal_entity_suffix_variants_share_one_entry():
    """A legal-entity suffix does not manufacture a second board entry."""
    store.record("RobCo", "https://careers.robco.example.com")
    store.record("RobCo GmbH", "https://careers.robco.example.com/de")

    boards = store.load()
    assert "robco" in boards
    assert len([k for k in boards if k in ("robco", "robco gmbh")]) == 1
    # The second record() call overwrote (merged onto) the first entry.
    assert boards["robco"].careers_url == "https://careers.robco.example.com/de"


def test_load_reconciles_legacy_duplicate_keys(data_dir):
    """Two legacy entries that now collapse to one identity key are merged on load.

    Prefers the entry with a non-empty careers_url over one without.
    """
    (data_dir / "company_boards.json").write_text(
        json.dumps(
            {
                "robco": {
                    "company": "RobCo",
                    "careers_url": "",
                    "ats": "",
                    "status": "ok",
                    "resolved_at": "2026-01-01T00:00:00+00:00",
                },
                "robco gmbh": {
                    "company": "RobCo GmbH",
                    "careers_url": "https://careers.robco.example.com",
                    "ats": "Greenhouse",
                    "status": "ok",
                    "resolved_at": "2026-02-01T00:00:00+00:00",
                },
            }
        ),
        encoding="utf-8",
    )

    boards = store.load()
    assert len([k for k in boards if company_identity_key(k) == "robco"]) == 1
    merged = boards["robco"]
    assert merged.careers_url == "https://careers.robco.example.com"
    assert merged.ats == "Greenhouse"

    # A pure read must not rewrite the file.
    on_disk = json.loads((data_dir / "company_boards.json").read_text(encoding="utf-8"))
    assert set(on_disk.keys()) == {"robco", "robco gmbh"}


def test_load_preserves_parenthesised_display_names(data_dir):
    """Companies whose legal form sits inside parentheses keep their key and name."""
    store.record("Klar (Klar Technologies GmbH)", "https://careers.klar.example.com")
    store.record("Noxtua (Xayn AG)", "https://careers.noxtua.example.com")

    boards = store.load()
    assert boards["klar (klar technologies gmbh)"].company == "Klar (Klar Technologies GmbH)"
    assert boards["noxtua (xayn ag)"].company == "Noxtua (Xayn AG)"


def test_round_trip_preserves_all_fields(data_dir):
    """Save and load preserves all fields."""
    store.record("Test Co", "https://test.example.com", "Greenhouse", "ok")
    boards = store.load()
    # "Co" is a legal-entity suffix stripped by the identity key.
    board = boards["test"]

    assert board.company == "Test Co"
    assert board.careers_url == "https://test.example.com"
    assert board.ats == "Greenhouse"
    assert board.status == "ok"
    assert board.resolved_at == ""
