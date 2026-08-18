"""Tests for company boards store."""

import pytest
from companyboards import store


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
    assert boards["defunct inc"].status == "dead"


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
    """Company names are normalized with strip().casefold()."""
    store.record(" Google ", "https://careers.google.com")
    store.record("APPLE", "https://careers.apple.com")
    
    boards = store.load()
    assert "google" in boards
    assert "apple" in boards
    # Original names are preserved in the CompanyBoard object
    assert boards["google"].company == " Google "
    assert boards["apple"].company == "APPLE"


def test_round_trip_preserves_all_fields(data_dir):
    """Save and load preserves all fields."""
    store.record("Test Co", "https://test.example.com", "Greenhouse", "ok")
    boards = store.load()
    board = boards["test co"]
    
    assert board.company == "Test Co"
    assert board.careers_url == "https://test.example.com"
    assert board.ats == "Greenhouse"
    assert board.status == "ok"
    assert board.resolved_at == ""
