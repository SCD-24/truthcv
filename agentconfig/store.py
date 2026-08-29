"""Agent configuration store. Storage: data_dir()/agent_config.json; env fallback remains the agent's default."""

from __future__ import annotations

import json
import zoneinfo
from dataclasses import dataclass, field
from pathlib import Path

from agentconfig.boards import DEFAULT_BOARD_SOURCES, catalog_mode
from screening.company import company_identity_key
from storage import data_dir


def config_path() -> Path:
    return data_dir() / "agent_config.json"


def _is_string_list(value: object) -> bool:
    """Check if value is a list containing only strings."""
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _dedupe_boards(boards: list["JobBoard"]) -> list["JobBoard"]:
    """De-duplicate JobBoards by casefolded source, first entry wins, order preserved."""
    seen: set[str] = set()
    result = []
    for board in boards:
        key = board.source.strip().casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(board)
    return result


@dataclass
class JobBoard:
    """One job board the operator has configured beyond the always-searched defaults.

    ``mode`` is only meaningful for a custom (non-catalog) board: "dork"
    searches it via Google, "direct" has the agent search the board's own
    site. A catalog board's effective mode is fixed and computed at resolve
    time (see AgentConfig.resolved_boards()) regardless of what is stored
    here — this field only ever drives behaviour for a custom source.
    """

    source: str = ""
    signin_url: str = ""
    mode: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "JobBoard":
        """Construct from a dict, ignoring unknown keys and falling back to defaults on wrong types."""
        kwargs = {}
        if "source" in raw and isinstance(raw["source"], str):
            kwargs["source"] = raw["source"]
        if "signin_url" in raw and isinstance(raw["signin_url"], str):
            kwargs["signin_url"] = raw["signin_url"]
        if "mode" in raw and isinstance(raw["mode"], str):
            kwargs["mode"] = raw["mode"]
        return cls(**kwargs)

    def to_dict(self) -> dict:
        """Serialize to a dict with snake_case keys."""
        return {"source": self.source, "signin_url": self.signin_url, "mode": self.mode}


@dataclass
class JobProfile:
    """Job search profile with search criteria and requirements."""

    name: str = ""
    enabled: bool = True
    # Search group
    keywords: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
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

        # keywords, locations: list[str]
        for field_name in ("keywords", "locations"):
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
    # Wall-clock IANA timezone that the run_at slots are interpreted in
    # (e.g. "Europe/Berlin"). Defaults to UTC so existing schedules keep
    # firing at exactly the same instant they do today.
    run_timezone: str = "UTC"
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
    # The operator's OWN boards, beyond the four defaults. The defaults
    # (agentconfig.boards.DEFAULT_BOARD_SOURCES) are unioned in at resolve
    # time via resolved_board_sources(), never stored here, so they are
    # always searched and cannot be lost to a bad PUT or a hand-edited file.
    job_boards: list[JobBoard] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        """Whether a scheduled run does anything at all.

        Derived rather than stored: two writers for one piece of state is how
        they diverge. Every existing consumer — agent/agent-config.js, the
        run gate in agent/daily-apply.sh, the Agents page's Run now section —
        reads this and keeps working unchanged.
        """
        return self.mode != "off"

    def resolved_board_sources(self) -> list[str]:
        """Job board sources actually searched: the four defaults, then the operator's own.

        The one place the union is expressed, so discovery (agentconfig/dorks.py)
        and the API cannot drift apart on what "the boards" means.
        """
        result = list(DEFAULT_BOARD_SOURCES)
        seen = {s.casefold() for s in DEFAULT_BOARD_SOURCES}
        for board in self.job_boards:
            key = board.source.strip().casefold()
            if key and key not in seen:
                seen.add(key)
                result.append(board.source)
        return result

    def resolved_boards(self) -> list[JobBoard]:
        """Job boards actually searched, defaults-first, each carrying its effective mode.

        Mirrors resolved_board_sources()'s defaults-first union but returns
        full JobBoard records (source, signin_url, effective mode) instead of
        bare source strings. Effective mode is the catalog's fixed mode for a
        catalog source (agentconfig.boards.catalog_mode), else the board's
        own stored mode, else "dork" — the behaviour every board had before
        modes existed.
        """
        overrides = {b.source.strip().casefold(): b for b in self.job_boards if b.source.strip()}
        result: list[JobBoard] = []
        seen: set[str] = set()
        for source in DEFAULT_BOARD_SOURCES:
            key = source.strip().casefold()
            seen.add(key)
            override = overrides.get(key)
            signin_url = override.signin_url if override else ""
            result.append(
                JobBoard(source=source, signin_url=signin_url, mode=catalog_mode(source) or "dork")
            )
        for board in self.job_boards:
            key = board.source.strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            mode = catalog_mode(board.source) or (board.mode or "dork")
            result.append(JobBoard(source=board.source, signin_url=board.signin_url, mode=mode))
        return result

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

        # run_timezone: str. Accepted only when it names a real IANA zone;
        # a missing key or a garbage value leaves the dataclass default
        # "UTC" in place rather than raising.
        if "run_timezone" in raw:
            value = raw["run_timezone"]
            if isinstance(value, str) and value:
                try:
                    zoneinfo.ZoneInfo(value)
                except Exception:  # ZoneInfoNotFoundError, ValueError, or anything else
                    pass
                else:
                    kwargs["run_timezone"] = value

        # profiles: list[JobProfile]
        if "profiles" in raw:
            if isinstance(raw["profiles"], list):
                profiles = []
                for item in raw["profiles"]:
                    if isinstance(item, dict):
                        profiles.append(JobProfile.from_dict(item))
                kwargs["profiles"] = profiles

        # job_boards: list[JobBoard]. Each item may be a dict or a bare
        # string (JobBoard(source=item)) so a hand-edited config is
        # forgiving. Blank sources are dropped; duplicates (casefolded
        # source) are dropped, first entry wins.
        if "job_boards" in raw:
            boards: list[JobBoard] = []
            if isinstance(raw["job_boards"], list):
                for item in raw["job_boards"]:
                    if isinstance(item, dict):
                        board = JobBoard.from_dict(item)
                    elif isinstance(item, str):
                        board = JobBoard(source=item)
                    else:
                        continue
                    if not board.source.strip():
                        continue
                    boards.append(board)
            kwargs["job_boards"] = _dedupe_boards(boards)
        else:
            # Migrated from each profile's old preferred_sources when the
            # job_boards key is absent, so an existing config's discovery
            # behaviour survives the upgrade. The defaults are NOT seeded
            # here — they are added at resolve time by resolved_board_sources()
            # — so an empty result here is correct and simply means "just
            # the defaults".
            migrated: list[JobBoard] = []
            raw_profiles = raw.get("profiles")
            if isinstance(raw_profiles, list):
                for item in raw_profiles:
                    if isinstance(item, dict) and _is_string_list(item.get("preferred_sources")):
                        for source in item["preferred_sources"]:
                            # Migrated boards keep today's dork-based discovery
                            # so an existing config's behaviour is unchanged.
                            migrated.append(JobBoard(source=source, mode="dork"))
            kwargs["job_boards"] = _dedupe_boards(migrated)

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
            "run_timezone": self.run_timezone,
            "profiles": [p.to_dict() for p in self.profiles],
            "job_boards": [b.to_dict() for b in self.job_boards],
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

    Company matching: identity-key equality (screening.company.company_identity_key),
    the same key used by screening/cooldown.py, so a legal-entity suffix does
    not let a blocked company slip through under a slightly different name
    (blocking "RobCo" also blocks "RobCo GmbH"). Non-string or blank company
    returns False (checked before the key is computed).
    """
    if not isinstance(company, str) or not company.strip():
        return False

    company_key = company_identity_key(company)
    return any(
        company_identity_key(blocked) == company_key
        for blocked in cfg.blocked_companies
    )
