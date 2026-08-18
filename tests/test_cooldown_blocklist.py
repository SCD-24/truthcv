"""Blocklisted companies report permanent cooldown through every surface."""

from __future__ import annotations

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
    assert r.json() == {"inCooldown": True, "expires": None, "blocked": True}
    from mcp.tools_ledger import check_cooldown

    assert check_cooldown("Acme GmbH") == {"in_cooldown": True, "expires": None, "blocked": True}


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
