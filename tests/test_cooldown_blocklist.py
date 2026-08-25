"""Blocklisted companies report permanent cooldown through every surface."""

from __future__ import annotations

import yaml
import pytest
from fastapi.testclient import TestClient

from agentconfig import store as agent_config_store
from api.main import app
from screening.cooldown import cooldown


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def _block(data_dir, name):
    cfg = agent_config_store.load()
    cfg.blocked_companies = [name]
    agent_config_store.save(cfg)


def test_blocked_company_is_permanently_in_cooldown(data_dir):
    _block(data_dir, "Acme GmbH")
    status = cooldown("acme gmbh")
    assert status.in_cooldown is True
    assert status.blocked is True
    assert status.expires is None


def test_unblocked_company_unaffected(data_dir):
    _block(data_dir, "Acme GmbH")
    status = cooldown("Beta AG")
    assert status.in_cooldown is False
    assert status.blocked is False


def test_block_beats_role_narrowing(data_dir):
    _block(data_dir, "Acme GmbH")
    assert cooldown("Acme GmbH", role="Engineer").blocked is True


def test_api_and_tool_carry_blocked_flag(client, data_dir):
    _block(data_dir, "Acme GmbH")
    r = client.get("/api/cooldown", params={"company": "Acme GmbH"})
    # A blocklist entry has no cooldown window, so window stays None.
    assert r.json() == {
        "inCooldown": True,
        "expires": None,
        "blocked": True,
        "window": None,
    }
    from agenttools.tools_ledger import check_cooldown

    assert check_cooldown("Acme GmbH") == {
        "in_cooldown": True,
        "expires": None,
        "blocked": True,
        "window": None,
    }


def test_cooldown_days_from_agent_config(data_dir, monkeypatch):
    # Ensure env var is not set
    monkeypatch.delenv("APPLICATION_COOLDOWN_DAYS", raising=False)
    
    # Set config value
    cfg = agent_config_store.load()
    cfg.cooldown_days = 14
    agent_config_store.save(cfg)
    
    from screening.cooldown import application_cooldown_days
    assert application_cooldown_days() == 14


def test_cooldown_days_from_env_when_config_unset(data_dir, monkeypatch):
    # Ensure config has no value
    cfg = agent_config_store.load()
    cfg.cooldown_days = None
    agent_config_store.save(cfg)
    
    # Set env var
    monkeypatch.setenv("APPLICATION_COOLDOWN_DAYS", "21")
    
    from screening.cooldown import application_cooldown_days
    assert application_cooldown_days() == 21


def test_cooldown_days_defaults_to_90(data_dir, monkeypatch):
    # Ensure both config and env are unset
    cfg = agent_config_store.load()
    cfg.cooldown_days = None
    agent_config_store.save(cfg)
    monkeypatch.delenv("APPLICATION_COOLDOWN_DAYS", raising=False)
    
    from screening.cooldown import application_cooldown_days
    assert application_cooldown_days() == 90


# --- Two-window cooldown (same-role vs same-company) ------------------------


def _seed_application(data_dir, company, role, days_ago):
    """Persist one tracked application dated `days_ago` days before now."""
    from datetime import datetime, timedelta, timezone

    from applications import store as apps_store

    app_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    apps_store.create(
        {
            "id": f"app-{company}-{role}".replace(" ", "-").lower(),
            "company": company,
            "role": role,
            "application_date": app_date,
            "submitted": True,
        }
    )


def test_legacy_only_config_behaviour_unchanged(data_dir, monkeypatch):
    """With only the legacy window set, company+role and company-only agree."""
    monkeypatch.delenv("APPLICATION_COOLDOWN_DAYS", raising=False)
    cfg = agent_config_store.load()
    cfg.cooldown_days = 10
    cfg.cooldown_days_same_role = None
    cfg.cooldown_days_same_company = None
    agent_config_store.save(cfg)

    _seed_application(data_dir, "Acme", "Engineer", days_ago=5)
    with_role = cooldown("Acme", role="Engineer")
    without_role = cooldown("Acme")
    assert with_role.in_cooldown is True
    assert without_role.in_cooldown is True
    # Same legacy window on both sides -> identical expiry.
    assert with_role.expires == without_role.expires


def test_same_role_window_overrides_legacy_independently(data_dir, monkeypatch):
    """Each new window takes precedence over the legacy field on its own."""
    monkeypatch.delenv("APPLICATION_COOLDOWN_DAYS", raising=False)
    cfg = agent_config_store.load()
    cfg.cooldown_days = 100
    cfg.cooldown_days_same_role = 7
    cfg.cooldown_days_same_company = 40
    agent_config_store.save(cfg)

    _seed_application(data_dir, "Acme", "Engineer", days_ago=20)
    role_match = cooldown("Acme", role="engineer")   # case-insensitive match
    other_role = cooldown("Acme", role="Designer")
    company_only = cooldown("Acme")

    # Role-matched: applied 20 days ago; same-role window (7 days) has lapsed
    # but same-company (40 days) still blocks it — the later expiry wins and
    # it reports the company window.
    assert role_match.in_cooldown is True
    assert role_match.window == "same_company"

    # A genuinely different role at the same company: same-company window
    # (40 days) applies, application + 40 days, still in cooldown.
    assert other_role.window == "same_company"
    assert other_role.in_cooldown is True
    # All three calls share the same winning expiry (the company window).
    assert role_match.expires == other_role.expires == company_only.expires


def test_env_fallback_still_honoured_when_no_config(data_dir, monkeypatch):
    """No config value anywhere: APPLICATION_COOLDOWN_DAYS drives both windows."""
    cfg = agent_config_store.load()
    cfg.cooldown_days = None
    cfg.cooldown_days_same_role = None
    cfg.cooldown_days_same_company = None
    agent_config_store.save(cfg)
    monkeypatch.setenv("APPLICATION_COOLDOWN_DAYS", "3")

    from screening.cooldown import application_cooldown_days, same_role_cooldown_days

    assert application_cooldown_days() == 3
    assert same_role_cooldown_days() == 3


def test_window_field_reported_for_each_case(data_dir, monkeypatch):
    """window names the winning window: role-matched, company-only, blocklist, clear."""
    monkeypatch.delenv("APPLICATION_COOLDOWN_DAYS", raising=False)
    cfg = agent_config_store.load()
    cfg.cooldown_days = 10
    agent_config_store.save(cfg)

    _seed_application(data_dir, "Acme", "Engineer", days_ago=5)

    role_match = cooldown("Acme", role="Engineer")
    assert role_match.in_cooldown is True
    assert role_match.window == "same_role"

    company_only = cooldown("Acme")
    assert company_only.in_cooldown is True
    assert company_only.window == "same_company"

    _block(data_dir, "BlockCo")
    blocked = cooldown("BlockCo")
    assert blocked.blocked is True
    assert blocked.window is None

    clear = cooldown("NeverApplied")
    assert clear.in_cooldown is False
    assert clear.window is None


# --- Company identity key: legal-entity suffixes match each other -----------


def test_application_to_bare_name_puts_suffixed_name_in_cooldown(data_dir, monkeypatch):
    """An application row for 'RobCo' also cools down 'RobCo GmbH'."""
    monkeypatch.delenv("APPLICATION_COOLDOWN_DAYS", raising=False)
    cfg = agent_config_store.load()
    cfg.cooldown_days = 30
    agent_config_store.save(cfg)

    _seed_application(data_dir, "RobCo", "Engineer", days_ago=5)

    status = cooldown("RobCo GmbH")
    assert status.in_cooldown is True
    assert status.blocked is False


def test_application_to_suffixed_name_puts_bare_name_in_cooldown(data_dir, monkeypatch):
    """An application row for 'RobCo GmbH' also cools down 'RobCo' (and vice versa)."""
    monkeypatch.delenv("APPLICATION_COOLDOWN_DAYS", raising=False)
    cfg = agent_config_store.load()
    cfg.cooldown_days = 30
    agent_config_store.save(cfg)

    _seed_application(data_dir, "RobCo GmbH", "Engineer", days_ago=5)

    status = cooldown("RobCo")
    assert status.in_cooldown is True
    assert status.blocked is False


def test_same_role_vs_same_company_window_selection_unaffected_by_suffix(
    data_dir, monkeypatch
):
    """Suffix-equivalence changes WHICH rows match, not which window wins."""
    monkeypatch.delenv("APPLICATION_COOLDOWN_DAYS", raising=False)
    cfg = agent_config_store.load()
    cfg.cooldown_days = 100
    cfg.cooldown_days_same_role = 7
    cfg.cooldown_days_same_company = 40
    agent_config_store.save(cfg)

    _seed_application(data_dir, "RobCo GmbH", "Engineer", days_ago=20)

    # Exact role match via the suffix-equivalent company: same-role window
    # (7 days) has lapsed but same-company (40 days) still blocks it.
    role_match = cooldown("RobCo", role="engineer")
    assert role_match.in_cooldown is True
    assert role_match.window == "same_company"

    # A different role at the suffix-equivalent company: same-company window.
    other_role = cooldown("RobCo", role="Designer")
    assert other_role.in_cooldown is True
    assert other_role.window == "same_company"


def test_blank_company_still_reports_no_cooldown_with_suffix_matching(data_dir):
    """A blank/whitespace company never matches anything, suffix key or not."""
    _seed_application(data_dir, "RobCo GmbH", "Engineer", days_ago=1)
    assert cooldown("").in_cooldown is False
    assert cooldown("   ").in_cooldown is False


def test_non_str_record_company_still_skipped_with_suffix_matching(data_dir):
    """A record with a non-str company is still skipped by the identity-key match."""
    from screening.cooldown import _matches

    assert _matches("RobCo GmbH", None, None, "Engineer") is False
    assert _matches("RobCo GmbH", None, 12345, "Engineer") is False
