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
        "runTimezone": "UTC",
        "profiles": [],
        "targetCompanies": [],
        "cooldownDays": None,
        "cooldownDaysSameRole": None,
        "cooldownDaysSameCompany": None,
        "maxApplicationsPerRun": None,
        "maxPostingAgeDays": None,
        "companyBoards": [],
        "mode": "full",
        "searchQueries": [],
        # Feed postings are opt-in (?include_feed=true) — a plain GET carries the
        # empty shape and never calls out to an API-backed board.
        "feedPostings": [],
        "feedError": "",
    }
    got = r.json()
    job_boards = got.pop("jobBoards")
    assert got == expected
    # The regression this build fixes: with no boards configured, the
    # sign-in list used to render nothing. GET must always return the four
    # defaults, each searchable and each with a real sign-in URL.
    assert len(job_boards) == 4
    assert {b["source"] for b in job_boards} == {"ashby", "greenhouse", "lever", "workday"}
    assert all(b["isDefault"] for b in job_boards)
    assert all(b["effectiveSigninUrl"] for b in job_boards)
    assert all(b["domain"] for b in job_boards)


def test_defaults_present_even_when_operator_configured_boards(client, data_dir):
    r = client.put("/api/agent/config", json={"jobBoards": [{"source": "linkedin"}]})
    assert r.status_code == 200
    sources = [b["source"] for b in r.json()["jobBoards"]]
    assert sources[:4] == ["ashby", "greenhouse", "lever", "workday"]
    assert "linkedin" in sources


def test_configuring_a_default_board_explicitly_does_not_duplicate_it(client, data_dir):
    r = client.put("/api/agent/config", json={"jobBoards": [{"source": "ashby"}]})
    assert r.status_code == 200
    sources = [b["source"] for b in r.json()["jobBoards"]]
    assert sources.count("ashby") == 1


def test_put_resolved_boards_back_does_not_persist_defaults_or_response_only_keys(client, data_dir):
    resolved = client.get("/api/agent/config").json()["jobBoards"]
    r = client.put("/api/agent/config", json={"jobBoards": resolved})
    assert r.status_code == 200

    import json as jsonlib
    from pathlib import Path

    stored = jsonlib.loads((Path(data_dir) / "agent_config.json").read_text())
    assert stored["job_boards"] == []
    for board in stored["job_boards"]:
        assert "domain" not in board
        assert "effective_signin_url" not in board
        assert "is_default" not in board


def test_put_default_board_with_signin_override_is_persisted(client, data_dir):
    resolved = client.get("/api/agent/config").json()["jobBoards"]
    for b in resolved:
        if b["source"] == "ashby":
            b["signinUrl"] = "https://custom.ashby.example/login"
    r = client.put("/api/agent/config", json={"jobBoards": resolved})
    assert r.status_code == 200
    ashby = next(b for b in r.json()["jobBoards"] if b["source"] == "ashby")
    assert ashby["effectiveSigninUrl"] == "https://custom.ashby.example/login"

    import json as jsonlib
    from pathlib import Path

    stored = jsonlib.loads((Path(data_dir) / "agent_config.json").read_text())
    assert any(b["source"] == "ashby" for b in stored["job_boards"])


def test_search_queries_source_follows_resolved_boards_not_profile(client, data_dir):
    r = client.put(
        "/api/agent/config",
        json={
            "jobBoards": [{"source": "linkedin"}],
            "profiles": [{"name": "p", "enabled": True, "keywords": ["backend"]}],
        },
    )
    assert r.status_code == 200
    sources = {q["source"] for q in client.get("/api/agent/config").json()["searchQueries"]}
    assert sources == {
        "jobs.ashbyhq.com",
        "job-boards.greenhouse.io",
        "jobs.lever.co",
        "myworkdayjobs.com",
        "linkedin.com/jobs",
    }


def test_old_shape_config_migrates_job_boards_on_first_get(client, data_dir):
    import json as jsonlib
    from pathlib import Path

    (Path(data_dir) / "agent_config.json").write_text(
        jsonlib.dumps({"profiles": [{"name": "p", "preferred_sources": ["linkedin"]}]})
    )
    got = client.get("/api/agent/config").json()
    sources = {b["source"]: b["isDefault"] for b in got["jobBoards"]}
    assert sources.get("linkedin") is False


def test_search_queries_populated_after_put_of_enabled_profile(client, data_dir):
    """searchQueries is empty with no profiles, non-empty after an enabled,
    keyword-bearing profile is PUT — and the PUT itself is not rejected by
    AgentConfigUpdate's extra='forbid' (search_queries is response-only)."""
    assert client.get("/api/agent/config").json()["searchQueries"] == []

    r = client.put(
        "/api/agent/config",
        json={
            "profiles": [
                {
                    "name": "Senior Python",
                    "enabled": True,
                    "keywords": ["platform engineer"],
                    "locations": ["Berlin"],
                }
            ]
        },
    )
    assert r.status_code == 200

    got = client.get("/api/agent/config").json()
    assert got["searchQueries"] != []
    assert got["searchQueries"][0]["query"].startswith("site:jobs.ashbyhq.com")


def test_profile_search_fields_round_trip_through_put_and_get(client, data_dir):
    """keywords and locations survive a PUT then GET round-trip on the wire,
    under their camelCase aliases. Sources are no longer per-profile — see
    the jobBoards tests."""
    r = client.put(
        "/api/agent/config",
        json={
            "profiles": [
                {
                    "name": "Senior Python",
                    "enabled": True,
                    "keywords": ["Python", "FastAPI"],
                    "locations": ["Berlin", "Remote"],
                }
            ]
        },
    )
    assert r.status_code == 200
    profile = r.json()["profiles"][0]
    assert profile["keywords"] == ["Python", "FastAPI"]
    assert profile["locations"] == ["Berlin", "Remote"]

    got_profile = client.get("/api/agent/config").json()["profiles"][0]
    assert got_profile["keywords"] == ["Python", "FastAPI"]
    assert got_profile["locations"] == ["Berlin", "Remote"]


def test_job_boards_round_trip_source_and_signin_url(client, data_dir):
    """jobBoards survive a PUT then GET round-trip: a known non-default
    source and a custom domain with an explicit signinUrl."""
    r = client.put(
        "/api/agent/config",
        json={
            "jobBoards": [
                {"source": "linkedin"},
                {"source": "jobs.acme.com", "signinUrl": "https://acme.com/login"},
            ]
        },
    )
    assert r.status_code == 200
    got = {b["source"]: b for b in client.get("/api/agent/config").json()["jobBoards"]}
    assert got["linkedin"]["isDefault"] is False
    assert got["jobs.acme.com"]["signinUrl"] == "https://acme.com/login"
    assert got["jobs.acme.com"]["effectiveSigninUrl"] == "https://acme.com/login"


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


def test_put_run_timezone_accepts_valid_zone(client, data_dir):
    r = client.put("/api/agent/config", json={"runTimezone": "Europe/Berlin"})
    assert r.status_code == 200
    assert r.json()["runTimezone"] == "Europe/Berlin"


def test_put_run_timezone_rejects_unknown_zone(client, data_dir):
    assert client.put("/api/agent/config", json={"runTimezone": "Mars/Olympus"}).status_code == 422


def test_put_omitting_run_timezone_leaves_stored_zone_untouched(client, data_dir):
    """PUT merges: an unrelated edit must not reset a stored timezone."""
    r = client.put("/api/agent/config", json={"runTimezone": "Europe/Berlin"})
    assert r.status_code == 200
    client.put("/api/agent/config", json={"runAt": ["10:00"]})
    assert client.get("/api/agent/config").json()["runTimezone"] == "Europe/Berlin"


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


def test_get_returns_resolved_boards_for_suffix_equivalent_target_company(client, data_dir):
    """A target company matches a board recorded under a legal-entity-suffix variant.

    The match is by identity key (screening.company.company_identity_key), so
    a target company "RobCo" also picks up a board recorded as "RobCo GmbH".
    """
    from companyboards import store as board_store

    r = client.put("/api/agent/config", json={"targetCompanies": ["RobCo"]})
    assert r.status_code == 200

    board_store.record("RobCo GmbH", "https://careers.robco.example.com", "Greenhouse")
    board_store.record("Microsoft", "https://careers.microsoft.com", "Workable")

    r = client.get("/api/agent/config")
    assert r.status_code == 200
    boards = r.json()["companyBoards"]
    company_names = {b["company"] for b in boards}
    assert "RobCo GmbH" in company_names
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


# ---------------------------------------------------------------------------
# maxPostingAgeDays — the discovery freshness window
# ---------------------------------------------------------------------------

class TestMaxPostingAgeDays:
    def test_round_trips_through_put_and_get(self, client, data_dir):
        r = client.put("/api/agent/config", json={"maxPostingAgeDays": 14})
        assert r.status_code == 200
        assert r.json()["maxPostingAgeDays"] == 14
        assert client.get("/api/agent/config").json()["maxPostingAgeDays"] == 14

    def test_zero_is_accepted_and_means_no_window(self, client, data_dir):
        """0 is a real choice here, not a missing value — it disables the window."""
        r = client.put("/api/agent/config", json={"maxPostingAgeDays": 0})
        assert r.status_code == 200
        assert r.json()["maxPostingAgeDays"] == 0

    def test_null_clears_the_window(self, client, data_dir):
        """Emptying the box on the Agents page must actually unset the window.

        The route used to merge with exclude_none, so a null read as "not
        sent": the stored value survived and the UI repainted it next to a
        "saved" indicator, with no way back to unset.
        """
        client.put("/api/agent/config", json={"maxPostingAgeDays": 30})
        r = client.put("/api/agent/config", json={"maxPostingAgeDays": None})
        assert r.status_code == 200
        assert r.json()["maxPostingAgeDays"] is None
        assert client.get("/api/agent/config").json()["maxPostingAgeDays"] is None

    def test_omitting_the_key_still_leaves_the_window_alone(self, client, data_dir):
        """Clearing requires SENDING null — an unrelated PUT must not wipe it."""
        client.put("/api/agent/config", json={"maxPostingAgeDays": 21})
        client.put("/api/agent/config", json={"targetCompanies": ["Acme"]})
        assert client.get("/api/agent/config").json()["maxPostingAgeDays"] == 21

    def test_a_null_does_not_clear_unrelated_fields(self, client, data_dir):
        """Only the keys actually sent are touched."""
        client.put("/api/agent/config", json={"maxPostingAgeDays": 21, "cooldownDays": 45})
        client.put("/api/agent/config", json={"maxPostingAgeDays": None})
        body = client.get("/api/agent/config").json()
        assert body["maxPostingAgeDays"] is None
        assert body["cooldownDays"] == 45

    def test_negative_is_rejected(self, client, data_dir):
        assert client.put("/api/agent/config", json={"maxPostingAgeDays": -1}).status_code == 422

    def test_absurd_value_is_rejected(self, client, data_dir):
        """A typo'd 3650 must not read as a deliberate ten-year window."""
        assert client.put("/api/agent/config", json={"maxPostingAgeDays": 3650}).status_code == 422

    def test_defaults_to_null_when_never_configured(self, client, data_dir):
        assert client.get("/api/agent/config").json()["maxPostingAgeDays"] is None

    def test_window_reaches_the_composed_search_urls(self, client, data_dir):
        """The setting is only useful if it lands on the URLs the agent opens."""
        client.put(
            "/api/agent/config",
            json={
                "maxPostingAgeDays": 3,
                "profiles": [{"name": "p", "enabled": True, "keywords": ["backend"]}],
            },
        )
        queries = client.get("/api/agent/config").json()["searchQueries"]
        assert queries
        assert all("tbs=qdr:d3" in q["url"] for q in queries)

    def test_omitting_the_field_leaves_a_stored_window_untouched(self, client, data_dir):
        """PUT merges: an unrelated edit must not clear the window."""
        client.put("/api/agent/config", json={"maxPostingAgeDays": 21})
        client.put("/api/agent/config", json={"targetCompanies": ["Acme"]})
        assert client.get("/api/agent/config").json()["maxPostingAgeDays"] == 21
