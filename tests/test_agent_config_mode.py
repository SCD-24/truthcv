"""The agent's autonomy mode, and its migration from the old `enabled` flag.

`enabled` was a stored boolean and is now derived from `mode`. Existing configs
on the volume carry only `enabled`, so the migration in from_dict is what keeps
a running deployment behaving exactly as it did before the upgrade.
"""

from __future__ import annotations

from agentconfig.store import AgentConfig


def test_mode_defaults_to_full():
    assert AgentConfig().mode == "full"


def test_enabled_is_derived_from_mode():
    assert AgentConfig(mode="full").enabled is True
    assert AgentConfig(mode="semi").enabled is True
    assert AgentConfig(mode="off").enabled is False


def test_migrates_enabled_true_to_full():
    """A config written before modes existed keeps the behaviour it had."""
    assert AgentConfig.from_dict({"enabled": True}).mode == "full"


def test_migrates_enabled_false_to_off():
    assert AgentConfig.from_dict({"enabled": False}).mode == "off"


def test_explicit_mode_wins_over_a_stale_enabled():
    assert AgentConfig.from_dict({"enabled": True, "mode": "semi"}).mode == "semi"


def test_unknown_mode_falls_back_to_full():
    """A malformed config must not silently disable the agent.

    A present-but-invalid mode forces the default; it never defers to enabled.
    """
    assert AgentConfig.from_dict({"mode": "sideways"}).mode == "full"
    assert AgentConfig.from_dict({"mode": 3}).mode == "full"
    # Invalid mode alongside enabled: mode presence wins, enabled is ignored
    assert AgentConfig.from_dict({"mode": "sideways", "enabled": False}).mode == "full"
    assert AgentConfig.from_dict({"mode": "sideways", "enabled": True}).mode == "full"


def test_to_dict_carries_mode_and_derived_enabled():
    d = AgentConfig(mode="semi").to_dict()
    assert d["mode"] == "semi"
    assert d["enabled"] is True
