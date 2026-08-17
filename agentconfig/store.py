"""Agent configuration store. Storage: data_dir()/agent_config.json; env fallback remains the agent's default."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from truth.store import data_dir


def config_path() -> Path:
    return data_dir() / "agent_config.json"


@dataclass
class AgentConfig:
    """Agent configuration: enabled flag, blocklist, and schedule."""

    enabled: bool = True
    blocked_companies: list[str] = field(default_factory=list)
    run_at: list[str] = field(default_factory=lambda: ["09:00", "15:00"])
    run_days: list[str] = field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])

    @classmethod
    def from_dict(cls, raw: dict) -> AgentConfig:
        """Construct from a dict, ignoring unknown keys and falling back to defaults on wrong types."""
        kwargs = {}

        # enabled: bool
        if "enabled" in raw and isinstance(raw["enabled"], bool):
            kwargs["enabled"] = raw["enabled"]

        # blocked_companies: list[str]
        if "blocked_companies" in raw:
            if isinstance(raw["blocked_companies"], list):
                kwargs["blocked_companies"] = raw["blocked_companies"]

        # run_at: list[str]
        if "run_at" in raw:
            if isinstance(raw["run_at"], list):
                kwargs["run_at"] = raw["run_at"]

        # run_days: list[str]
        if "run_days" in raw:
            if isinstance(raw["run_days"], list):
                kwargs["run_days"] = raw["run_days"]

        return cls(**kwargs)

    def to_dict(self) -> dict:
        """Serialize to a dict with snake_case keys."""
        return {
            "enabled": self.enabled,
            "blocked_companies": self.blocked_companies,
            "run_at": self.run_at,
            "run_days": self.run_days,
        }


def load() -> AgentConfig:
    """Load the agent config from agent_config.json.

    Returns defaults if file is missing, corrupt, or not a dict.
    """
    p = config_path()
    if not p.exists():
        return AgentConfig()

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return AgentConfig()

    if not isinstance(raw, dict):
        return AgentConfig()

    return AgentConfig.from_dict(raw)


def save(cfg: AgentConfig) -> AgentConfig:
    """Atomically write the agent config to agent_config.json. Returns it."""
    p = config_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(cfg.to_dict(), indent=2),
        encoding="utf-8",
    )
    tmp.replace(p)
    return cfg


def is_blocked(cfg: AgentConfig, company: str) -> bool:
    """Check if a company is blocked.

    Company matching: strip/casefold equality like screening/cooldown.py.
    Non-string or blank company returns False.
    """
    if not isinstance(company, str) or not company.strip():
        return False

    company_normalized = company.strip().casefold()
    return any(
        blocked.strip().casefold() == company_normalized
        for blocked in cfg.blocked_companies
    )
