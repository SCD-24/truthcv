"""/api/agent/config: defaults, merge-on-PUT, validation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def test_get_returns_defaults(client, data_dir):
    r = client.get("/api/agent/config")
    assert r.status_code == 200
    expected = {
        "enabled": True,
        "blockedCompanies": [],
        "runAt": ["09:00", "15:00"],
        "runDays": ["mon", "tue", "wed", "thu", "fri"],
        "profiles": [],
        "targetCompanies": [],
        "cooldownDays": None,
        "cooldownDaysSameRole": None,
        "cooldownDaysSameCompany": None,
        "maxApplicationsPerRun": None,
        "companyBoards": [],
        "mode": "full",
    }
    assert r.json() == expected


def test_put_merges_partial(client, data_dir):
    r = client.put("/api/agent/config", json={"mode": "off"})
    assert r.status_code == 200
    assert r.json()["mode"] == "off"
    assert r.json()["runAt"] == ["09:00", "15:00"]  # untouched


def test_put_blocklist_strips_and_drops_empties(client, data_dir):
    r = client.put("/api/agent/config", json={"blockedCompanies": [" Acme ", "", "  "]})
    assert r.json()["blockedCompanies"] == ["Acme"]


def test_put_rejects_bad_time(client, data_dir):
    assert client.put("/api/agent/config", json={"runAt": ["9:00"]}).status_code == 422
    assert client.put("/api/agent/config", json={"runAt": ["25:00"]}).status_code == 422
    assert client.put("/api/agent/config", json={"runAt": []}).status_code == 422


def test_put_rejects_bad_day(client, data_dir):
    assert client.put("/api/agent/config", json={"runDays": ["monday"]}).status_code == 422
    assert client.put("/api/agent/config", json={"runDays": []}).status_code == 422


def test_put_dedups_run_days_preserving_order(client, data_dir):
    r = client.put("/api/agent/config", json={"runDays": ["mon", "mon", "tue"]})
    assert r.status_code == 200
    assert r.json()["runDays"] == ["mon", "tue"]


def test_put_explicit_nulls_do_not_reset_fields(client, data_dir):
    r = client.put(
        "/api/agent/config",
        json={"mode": "off", "blockedCompanies": ["Acme"]},
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "off"
    assert r.json()["blockedCompanies"] == ["Acme"]

    r = client.put(
        "/api/agent/config",
        json={"mode": None, "blockedCompanies": None},
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "off"
    assert r.json()["blockedCompanies"] == ["Acme"]


def test_put_target_companies_accepts_comma_delimited_string(client, data_dir):
    r = client.put("/api/agent/config", json={"targetCompanies": "Google, Acme GmbH, Apple"})
    assert r.status_code == 200
    assert r.json()["targetCompanies"] == ["Google", "Acme GmbH", "Apple"]


def test_put_target_companies_accepts_list(client, data_dir):
    r = client.put("/api/agent/config", json={"targetCompanies": ["Google", "Acme"]})
    assert r.status_code == 200
    assert r.json()["targetCompanies"] == ["Google", "Acme"]


def test_put_rejects_cooldown_days_negative(client, data_dir):
    assert client.put("/api/agent/config", json={"cooldownDays": -1}).status_code == 422


def test_put_accepts_cooldown_days_zero_and_positive(client, data_dir):
    r = client.put("/api/agent/config", json={"cooldownDays": 0})
    assert r.status_code == 200
    assert r.json()["cooldownDays"] == 0

    r = client.put("/api/agent/config", json={"cooldownDays": 30})
    assert r.status_code == 200
    assert r.json()["cooldownDays"] == 30


def test_put_rejects_max_applications_per_run_less_than_one(client, data_dir):
    assert client.put("/api/agent/config", json={"maxApplicationsPerRun": 0}).status_code == 422
    assert client.put("/api/agent/config", json={"maxApplicationsPerRun": -5}).status_code == 422


def test_put_accepts_max_applications_per_run_one_or_more(client, data_dir):
    r = client.put("/api/agent/config", json={"maxApplicationsPerRun": 1})
    assert r.status_code == 200
    assert r.json()["maxApplicationsPerRun"] == 1

    r = client.put("/api/agent/config", json={"maxApplicationsPerRun": 10})
    assert r.status_code == 200
    assert r.json()["maxApplicationsPerRun"] == 10


def test_put_rejects_profile_with_empty_name(client, data_dir):
    r = client.put(
        "/api/agent/config",
        json={"profiles": [{"name": "", "enabled": True}]},
    )
    assert r.status_code == 422


def test_put_rejects_duplicate_profile_names(client, data_dir):
    r = client.put(
        "/api/agent/config",
        json={
            "profiles": [
                {"name": "Senior Python", "enabled": True},
                {"name": "Senior Python", "enabled": False},
            ]
        },
    )
    assert r.status_code == 422


def test_put_rejects_salary_values_not_greater_than_zero(client, data_dir):
    r = client.put(
        "/api/agent/config",
        json={"profiles": [{"name": "Test", "salaryFloor": 0}]},
    )
    assert r.status_code == 422

    r = client.put(
        "/api/agent/config",
        json={"profiles": [{"name": "Test", "salaryAskMin": -1000}]},
    )
    assert r.status_code == 422


def test_put_rejects_salary_ordering_violations(client, data_dir):
    # floor > ask_min
    r = client.put(
        "/api/agent/config",
        json={
            "profiles": [
                {
                    "name": "Test",
                    "salaryFloor": 100000,
                    "salaryAskMin": 90000,
                }
            ]
        },
    )
    assert r.status_code == 422

    # ask_min > ask_max
    r = client.put(
        "/api/agent/config",
        json={
            "profiles": [
                {
                    "name": "Test",
                    "salaryAskMin": 110000,
                    "salaryAskMax": 100000,
                }
            ]
        },
    )
    assert r.status_code == 422


def test_put_accepts_valid_salary_range(client, data_dir):
    r = client.put(
        "/api/agent/config",
        json={
            "profiles": [
                {
                    "name": "Senior Python",
                    "salaryFloor": 90000,
                    "salaryAskMin": 100000,
                    "salaryAskMax": 130000,
                }
            ]
        },
    )
    assert r.status_code == 200
    profile = r.json()["profiles"][0]
    assert profile["salaryFloor"] == 90000
    assert profile["salaryAskMin"] == 100000
    assert profile["salaryAskMax"] == 130000


def test_currency_survives_the_wire_and_defaults_to_none(client, data_dir):
    """A profile's currency must round-trip through PUT and GET.

    recommend_salary formats its figure with the profile's currency, so a save
    that silently reset it to a regional default would make the agent quote
    the wrong unit. A profile saved without a currency stays unset (None) —
    there is no eurozone default to inherit.
    """
    r = client.put(
        "/api/agent/config",
        json={"profiles": [{"name": "UK", "currency": "GBP", "salaryAskMin": 80000}]},
    )
    assert r.status_code == 200
    assert r.json()["profiles"][0]["currency"] == "GBP"

    assert client.get("/api/agent/config").json()["profiles"][0]["currency"] == "GBP"

    r = client.put("/api/agent/config", json={"profiles": [{"name": "Default"}]})
    assert r.json()["profiles"][0]["currency"] is None


def test_put_rejects_glassdoor_min_out_of_range(client, data_dir):
    r = client.put(
        "/api/agent/config",
        json={"profiles": [{"name": "Test", "glassdoorMin": -0.5}]},
    )
    assert r.status_code == 422

    r = client.put(
        "/api/agent/config",
        json={"profiles": [{"name": "Test", "glassdoorMin": 5.5}]},
    )
    assert r.status_code == 422


def test_put_accepts_glassdoor_min_in_range(client, data_dir):
    r = client.put(
        "/api/agent/config",
        json={"profiles": [{"name": "Test", "glassdoorMin": 3.5}]},
    )
    assert r.status_code == 200
    assert r.json()["profiles"][0]["glassdoorMin"] == 3.5


def test_get_returns_resolved_boards_for_target_companies(client, data_dir):
    """GET /api/agent/config includes resolved boards for watchlist companies."""
    from companyboards import store as board_store
    
    # Configure target companies
    r = client.put("/api/agent/config", json={"targetCompanies": ["Google", "Apple"]})
    assert r.status_code == 200
    
    # Record boards
    board_store.record("Google", "https://careers.google.com", "Lever")
    board_store.record("Apple", "https://careers.apple.com", "Greenhouse")
    board_store.record("Microsoft", "https://careers.microsoft.com", "Workable")
    
    # GET should return only Google and Apple boards
    r = client.get("/api/agent/config")
    assert r.status_code == 200
    boards = r.json()["companyBoards"]
    company_names = {b["company"] for b in boards}
    assert "Google" in company_names
    assert "Apple" in company_names
    assert "Microsoft" not in company_names


def test_get_omits_boards_for_removed_target_companies(client, data_dir):
    """Boards for companies removed from watchlist are pruned."""
    from companyboards import store as board_store
    
    # Set targets
    client.put("/api/agent/config", json={"targetCompanies": ["Google"]})
    
    # Record board
    board_store.record("Google", "https://careers.google.com")
    
    # Verify it's returned
    r = client.get("/api/agent/config")
    assert len(r.json()["companyBoards"]) == 1
    
    # Remove from watchlist
    client.put("/api/agent/config", json={"targetCompanies": []})
    
    # Board should be pruned
    r = client.get("/api/agent/config")
    assert len(r.json()["companyBoards"]) == 0


def test_put_rejects_unknown_fields_including_company_boards(client, data_dir):
    """PUT /api/agent/config rejects any undeclared field, companyBoards included.

    AgentConfigUpdate sets extra="forbid" (needed to reject writes to the
    derived `enabled` field), so this 422s for the same reason it would for
    any field nobody has ever heard of — that part of the coverage is generic,
    not companyBoards-specific. What IS specific to companyBoards is the
    second assertion below: it is a server-resolved, read-only field, so it
    must never land in the stored config even if the reject-unknown-fields
    behavior above were ever loosened.
    """
    from agentconfig import store as agent_config_store

    r = client.put(
        "/api/agent/config",
        json={"companyBoards": [{"company": "Fake", "careersUrl": "fake.com"}]},
    )
    assert r.status_code == 422
    # companyBoards should not be in the stored config
    assert "company_boards" not in agent_config_store.load().to_dict()


def test_put_profiles_replace_wholesale_not_merge(client, data_dir):
    # First PUT: store a profile
    r = client.put(
        "/api/agent/config",
        json={"profiles": [{"name": "Profile1", "enabled": True}]},
    )
    assert r.status_code == 200
    assert len(r.json()["profiles"]) == 1
    assert r.json()["profiles"][0]["name"] == "Profile1"

    # Second PUT with a different profile list: should replace, not append
    r = client.put(
        "/api/agent/config",
        json={"profiles": [{"name": "Profile2", "enabled": False}]},
    )
    assert r.status_code == 200
    assert len(r.json()["profiles"]) == 1
    assert r.json()["profiles"][0]["name"] == "Profile2"
    assert r.json()["profiles"][0]["enabled"] is False


def test_put_schedule_only_leaves_profiles_intact(client, data_dir):
    # Store both profiles and schedule
    r = client.put(
        "/api/agent/config",
        json={
            "profiles": [{"name": "Senior Python", "enabled": True}],
            "runAt": ["09:00"],
            "runDays": ["mon", "tue"],
        },
    )
    assert r.status_code == 200
    assert len(r.json()["profiles"]) == 1
    assert r.json()["profiles"][0]["name"] == "Senior Python"
    assert r.json()["runAt"] == ["09:00"]

    # PUT only the schedule (no profiles field)
    r = client.put(
        "/api/agent/config",
        json={"runAt": ["14:00"]},
    )
    assert r.status_code == 200
    # Profiles should remain unchanged
    assert len(r.json()["profiles"]) == 1
    assert r.json()["profiles"][0]["name"] == "Senior Python"
    # Schedule should be updated
    assert r.json()["runAt"] == ["14:00"]
    assert r.json()["runDays"] == ["mon", "tue"]  # unchanged from before


def test_put_target_companies_and_globals_merge_separately(client, data_dir):
    # Store all fields
    r = client.put(
        "/api/agent/config",
        json={
            "targetCompanies": ["Google", "Apple"],
            "cooldownDays": 30,
            "maxApplicationsPerRun": 5,
        },
    )
    assert r.status_code == 200
    assert r.json()["targetCompanies"] == ["Google", "Apple"]
    assert r.json()["cooldownDays"] == 30
    assert r.json()["maxApplicationsPerRun"] == 5

    # PUT only cooldownDays
    r = client.put(
        "/api/agent/config",
        json={"cooldownDays": 14},
    )
    assert r.status_code == 200
    # Both other fields should remain unchanged
    assert r.json()["targetCompanies"] == ["Google", "Apple"]
    assert r.json()["cooldownDays"] == 14
    assert r.json()["maxApplicationsPerRun"] == 5


def test_put_accepts_new_cooldown_windows(client, data_dir):
    """cooldownDaysSameRole / cooldownDaysSameCompany round-trip through PUT/GET."""
    r = client.put(
        "/api/agent/config",
        json={"cooldownDaysSameRole": 90, "cooldownDaysSameCompany": 30},
    )
    assert r.status_code == 200
    assert r.json()["cooldownDaysSameRole"] == 90
    assert r.json()["cooldownDaysSameCompany"] == 30
    got = client.get("/api/agent/config").json()
    assert got["cooldownDaysSameRole"] == 90
    assert got["cooldownDaysSameCompany"] == 30


def test_put_rejects_negative_cooldown_windows(client, data_dir):
    for field in ("cooldownDaysSameRole", "cooldownDaysSameCompany"):
        r = client.put("/api/agent/config", json={field: -1})
        assert r.status_code == 422, field


def test_omitted_cooldown_window_leaves_stored_value(data_dir, client):
    """Merge semantics: an omitted window keeps its stored value."""
    client.put("/api/agent/config", json={"cooldownDaysSameRole": 90})
    # A later PUT that omits the window must not reset it.
    r = client.put("/api/agent/config", json={"mode": "semi"})
    assert r.status_code == 200
    assert r.json()["cooldownDaysSameRole"] == 90


def test_get_returns_mode_and_derived_enabled(client, data_dir):
    r = client.get("/api/agent/config")
    assert r.status_code == 200
    assert r.json()["mode"] == "full"
    assert r.json()["enabled"] is True


def test_put_sets_mode(client, data_dir):
    r = client.put("/api/agent/config", json={"mode": "semi"})
    assert r.status_code == 200
    assert r.json()["mode"] == "semi"
    assert r.json()["enabled"] is True
    assert client.get("/api/agent/config").json()["mode"] == "semi"


def test_put_off_derives_enabled_false(client, data_dir):
    assert client.put("/api/agent/config", json={"mode": "off"}).json()["enabled"] is False


def test_put_rejects_an_unknown_mode(client, data_dir):
    assert client.put("/api/agent/config", json={"mode": "sideways"}).status_code == 422


def test_put_ignores_enabled(client, data_dir):
    """`enabled` is derived. Accepting a write to it would give one piece of
    state two writers."""
    client.put("/api/agent/config", json={"mode": "semi"})
    r = client.put("/api/agent/config", json={"enabled": False})
    assert r.status_code == 422
    assert client.get("/api/agent/config").json()["mode"] == "semi"
