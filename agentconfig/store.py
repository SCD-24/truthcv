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
    currency: str | None = None
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

        # currency: str
        if "currency" in raw and isinstance(raw["currency"], str):
            kwargs["currency"] = raw["currency"]

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
            "currency": self.currency,
            "working_language": self.working_language,
            "glassdoor_min": self.glassdoor_min,
            "glassdoor_min_reviews": self.glassdoor_min_reviews,
            "accepted_role_types": self.accepted_role_types,
            "rejected_role_types": self.rejected_role_types,
        }


@dataclass
class AgentConfig:
    """Agent configuration: autonomy mode, blocklist, schedule, and job profiles."""

    MODES = ("off", "semi", "full")

    mode: str = "full"
    blocked_companies: list[str] = field(default_factory=list)
    run_at: list[str] = field(default_factory=lambda: ["09:00", "15:00"])
    run_days: list[str] = field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
    profiles: list[JobProfile] = field(default_factory=list)
    target_companies: list[str] = field(default_factory=list)
    cooldown_days: int | None = None
    # Per-window cooldown overrides. None means "inherit cooldown_days"
    # (which itself falls back to the env var and then 90), so an existing
    # data/agent_config.json behaves exactly as before these existed.
    cooldown_days_same_role: int | None = None
    cooldown_days_same_company: int | None = None
    max_applications_per_run: int | None = None
    # Discovery freshness window: only consider postings published within this
    # many days. None means "unset", which keeps the past-week window the dork
    # URLs have always carried; 0 disables the window entirely (any age),
    # mirroring how 0 disables a cooldown window.
    max_posting_age_days: int | None = None

    @property
    def enabled(self) -> bool:
        """Whether a scheduled run does anything at all.

        Derived rather than stored: two writers for one piece of state is how
        they diverge. Every existing consumer — agent/agent-config.js, the
        run gate in agent/daily-apply.sh, the Agents page's Run now section —
        reads this and keeps working unchanged.
        """
        return self.mode != "off"

    @classmethod
    def from_dict(cls, raw: dict) -> AgentConfig:
        """Construct from a dict, ignoring unknown keys and falling back to defaults on wrong types."""
        kwargs = {}

        # mode: str. Migrated from the pre-mode `enabled` boolean when absent,
        # so a config already on the volume keeps the behaviour it has: an
        # enabled agent was a full-auto agent. If a mode key is present—whether
        # valid or stale—it takes precedence and an unrecognised one falls back
        # to the default rather than deferring to enabled, which would silently
        # disable the agent if mode is corrupt and enabled is false.
        if "mode" in raw:
            if raw["mode"] in cls.MODES:
                kwargs["mode"] = raw["mode"]
        elif "enabled" in raw and isinstance(raw["enabled"], bool):
            kwargs["mode"] = "full" if raw["enabled"] else "off"

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

        # cooldown_days: int | None (legacy single window; still the fallback)
        if "cooldown_days" in raw and isinstance(raw["cooldown_days"], int):
            kwargs["cooldown_days"] = raw["cooldown_days"]

        # cooldown_days_same_role / cooldown_days_same_company: int | None
        for field_name in ("cooldown_days_same_role", "cooldown_days_same_company"):
            if field_name in raw:
                # Non-int values fall back to None rather than raising, so a
                # hand-edited config never blocks the run.
                kwargs[field_name] = raw[field_name] if isinstance(raw[field_name], int) else None

        # max_applications_per_run: int | None
        if "max_applications_per_run" in raw and isinstance(raw["max_applications_per_run"], int):
            kwargs["max_applications_per_run"] = raw["max_applications_per_run"]

        # max_posting_age_days: int | None. A value that is not a usable day
        # count falls back to None rather than raising, so a hand-edited config
        # never blocks the run.
        #
        # `isinstance(True, int)` is True in Python, so a bare isinstance check
        # stores the bool: `true` then rendered as the Google parameter
        # "qdr:dTrue", which Google ignores — silently widening discovery to all
        # time while the run prompt announced an active filter. Booleans are
        # excluded explicitly, and the API's own bounds are applied here too,
        # since this path reads the file directly and never sees the validator.
        if "max_posting_age_days" in raw:
            value = raw["max_posting_age_days"]
            usable = (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value <= 365
            )
            kwargs["max_posting_age_days"] = value if usable else None

        return cls(**kwargs)

    def to_dict(self) -> dict:
        """Serialize to a dict with snake_case keys."""
        return {
            "mode": self.mode,
            # Derived, not stored — emitted so existing readers of the wire
            # shape (agent-config.js, the Agents page) need no change.
            "enabled": self.enabled,
            "blocked_companies": self.blocked_companies,
            "run_at": self.run_at,
            "run_days": self.run_days,
            "profiles": [p.to_dict() for p in self.profiles],
            "target_companies": self.target_companies,
            "cooldown_days": self.cooldown_days,
            "cooldown_days_same_role": self.cooldown_days_same_role,
            "cooldown_days_same_company": self.cooldown_days_same_company,
            "max_applications_per_run": self.max_applications_per_run,
            "max_posting_age_days": self.max_posting_age_days,
        }

    def _storage_dict(self) -> dict:
        """On-disk shape — distinct from `to_dict()`'s wire shape.

        Here `enabled` means `mode == "full"`, not the wire meaning
        (`mode != "off"`). A pre-mode build only ever reads `enabled`, so this
        is what makes a rollback fail closed: both `semi` and `off` land back
        on a disabled agent, and only `full` survives a rollback still
        running. Storing the wire meaning instead would roll a `semi` config
        back to a fully autonomous one — the opposite of fail-closed.
        """
        d = self.to_dict()
        d["enabled"] = self.mode == "full"
        return d


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
        json.dumps(cfg._storage_dict(), indent=2),
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
