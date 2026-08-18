"""Agent configuration store. Storage: data_dir()/agent_config.json; env fallback remains the agent's default."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from truth.store import data_dir


def config_path() -> Path:
    return data_dir() / "agent_config.json"


def _is_string_list(value: object) -> bool:
    """Check if value is a list containing only strings."""
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


@dataclass
class JobProfile:
    """Job search profile with search criteria and requirements."""

    name: str = ""
    enabled: bool = True
    # Search group
    keywords: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    preferred_sources: list[str] = field(default_factory=list)
    # Requirement fields (all optional/nullable per spec)
    remote_model: str | None = None
    employment_country: str | None = None
    eor_allowed: bool | None = None
    require_entity_verification: bool = True
    salary_floor: int | None = None
    salary_ask_min: int | None = None
    salary_ask_max: int | None = None
    working_language: str | None = None
    glassdoor_min: float | None = None
    glassdoor_min_reviews: int | None = None
    accepted_role_types: list[str] = field(default_factory=list)
    rejected_role_types: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> JobProfile:
        """Construct from a dict, ignoring unknown keys and falling back to defaults on wrong types."""
        kwargs = {}

        # name: str
        if "name" in raw and isinstance(raw["name"], str):
            kwargs["name"] = raw["name"]

        # enabled: bool
        if "enabled" in raw and isinstance(raw["enabled"], bool):
            kwargs["enabled"] = raw["enabled"]

        # keywords, locations, preferred_sources: list[str]
        for field_name in ("keywords", "locations", "preferred_sources"):
            if field_name in raw:
                if _is_string_list(raw[field_name]):
                    kwargs[field_name] = raw[field_name]

        # remote_model, employment_country, working_language: str | None
        for field_name in ("remote_model", "employment_country", "working_language"):
            if field_name in raw and isinstance(raw[field_name], str):
                kwargs[field_name] = raw[field_name]

        # eor_allowed: bool | None
        if "eor_allowed" in raw and isinstance(raw["eor_allowed"], bool):
            kwargs["eor_allowed"] = raw["eor_allowed"]

        # require_entity_verification: bool
        if "require_entity_verification" in raw and isinstance(raw["require_entity_verification"], bool):
            kwargs["require_entity_verification"] = raw["require_entity_verification"]

        # salary_floor, salary_ask_min, salary_ask_max, glassdoor_min_reviews: int | None
        for field_name in ("salary_floor", "salary_ask_min", "salary_ask_max", "glassdoor_min_reviews"):
            if field_name in raw and isinstance(raw[field_name], int):
                kwargs[field_name] = raw[field_name]

        # glassdoor_min: float | None
        if "glassdoor_min" in raw and isinstance(raw["glassdoor_min"], (int, float)):
            kwargs["glassdoor_min"] = float(raw["glassdoor_min"])

        # accepted_role_types, rejected_role_types: list[str]
        for field_name in ("accepted_role_types", "rejected_role_types"):
            if field_name in raw:
                if _is_string_list(raw[field_name]):
                    kwargs[field_name] = raw[field_name]

        return cls(**kwargs)

    def to_dict(self) -> dict:
        """Serialize to a dict with snake_case keys."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "keywords": self.keywords,
            "locations": self.locations,
            "preferred_sources": self.preferred_sources,
            "remote_model": self.remote_model,
            "employment_country": self.employment_country,
            "eor_allowed": self.eor_allowed,
            "require_entity_verification": self.require_entity_verification,
            "salary_floor": self.salary_floor,
            "salary_ask_min": self.salary_ask_min,
            "salary_ask_max": self.salary_ask_max,
            "working_language": self.working_language,
            "glassdoor_min": self.glassdoor_min,
            "glassdoor_min_reviews": self.glassdoor_min_reviews,
            "accepted_role_types": self.accepted_role_types,
            "rejected_role_types": self.rejected_role_types,
        }


@dataclass
class AgentConfig:
    """Agent configuration: enabled flag, blocklist, schedule, and job profiles."""

    enabled: bool = True
    blocked_companies: list[str] = field(default_factory=list)
    run_at: list[str] = field(default_factory=lambda: ["09:00", "15:00"])
    run_days: list[str] = field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
    profiles: list[JobProfile] = field(default_factory=list)
    target_companies: list[str] = field(default_factory=list)
    cooldown_days: int | None = None
    max_applications_per_run: int | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> AgentConfig:
        """Construct from a dict, ignoring unknown keys and falling back to defaults on wrong types."""
        kwargs = {}

        # enabled: bool
        if "enabled" in raw and isinstance(raw["enabled"], bool):
            kwargs["enabled"] = raw["enabled"]

        # blocked_companies: list[str]
        if "blocked_companies" in raw:
            if _is_string_list(raw["blocked_companies"]):
                kwargs["blocked_companies"] = raw["blocked_companies"]

        # run_at: list[str]
        if "run_at" in raw:
            if _is_string_list(raw["run_at"]):
                kwargs["run_at"] = raw["run_at"]

        # run_days: list[str]
        if "run_days" in raw:
            if _is_string_list(raw["run_days"]):
                kwargs["run_days"] = raw["run_days"]

        # profiles: list[JobProfile]
        if "profiles" in raw:
            if isinstance(raw["profiles"], list):
                profiles = []
                for item in raw["profiles"]:
                    if isinstance(item, dict):
                        profiles.append(JobProfile.from_dict(item))
                kwargs["profiles"] = profiles

        # target_companies: list[str]
        if "target_companies" in raw:
            if _is_string_list(raw["target_companies"]):
                kwargs["target_companies"] = raw["target_companies"]

        # cooldown_days: int | None
        if "cooldown_days" in raw and isinstance(raw["cooldown_days"], int):
            kwargs["cooldown_days"] = raw["cooldown_days"]

        # max_applications_per_run: int | None
        if "max_applications_per_run" in raw and isinstance(raw["max_applications_per_run"], int):
            kwargs["max_applications_per_run"] = raw["max_applications_per_run"]

        return cls(**kwargs)

    def to_dict(self) -> dict:
        """Serialize to a dict with snake_case keys."""
        return {
            "enabled": self.enabled,
            "blocked_companies": self.blocked_companies,
            "run_at": self.run_at,
            "run_days": self.run_days,
            "profiles": [p.to_dict() for p in self.profiles],
            "target_companies": self.target_companies,
            "cooldown_days": self.cooldown_days,
            "max_applications_per_run": self.max_applications_per_run,
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
