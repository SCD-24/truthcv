"""Wire models for the agent: its config, LLM credentials, status and run accounting."""

from __future__ import annotations

import re
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from truthcv.domain.agentconfig.store import DORK_RECENCIES, AgentConfig

from .common import _Camel
from .jobs import (
    CompanyBoardModel,
    DirectBoardModel,
    FeedPostingModel,
    JobBoardModel,
    JobProfileModel,
    SearchQueryModel,
)


_RUN_AT_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


_RUN_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


class AgentConfigModel(_Camel):
    """GET /api/agent/config response: enabled flag, blocklist, schedule, job profiles, and resolved boards."""

    mode: str = "full"
    # Derived server-side from mode; present so existing readers need no change.
    enabled: bool = True
    blocked_companies: list[str] = Field(default_factory=list)
    run_at: list[str] = Field(default_factory=lambda: ["09:00", "15:00"])
    run_days: list[str] = Field(
        default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"]
    )
    run_timezone: str = "UTC"
    profiles: list[JobProfileModel] = Field(default_factory=list)
    job_boards: list[JobBoardModel] = Field(default_factory=list)
    target_companies: list[str] = Field(default_factory=list)
    cooldown_days: int | None = None
    cooldown_days_same_role: int | None = None
    cooldown_days_same_company: int | None = None
    max_applications_per_run: int | None = None
    max_posting_age_days: int | None = None
    dork_recency: str = "w"
    company_boards: list[CompanyBoardModel] = Field(default_factory=list)
    search_queries: list[SearchQueryModel] = Field(default_factory=list)
    # One entry per direct-mode board (searched on-site rather than via a
    # Google dork), with its URL, sign-in URL, and the enabled profiles'
    # search criteria for the agent to use there.
    direct_boards: list[DirectBoardModel] = Field(default_factory=list)
    # Postings pulled from API-backed boards. Populated only when the caller
    # asks for them (GET /agent/config?include_feed=true) — the web UI does
    # not, so loading a page never waits on a third-party API. feed_error
    # carries the first failure, so the Job boards page can say why the feed
    # is empty instead of implying there are no matching jobs.
    feed_postings: list[FeedPostingModel] = Field(default_factory=list)
    feed_error: str = ""
    # Count of feed postings dropped because the ledger already has a
    # screening for them (see screening.store.screened_dedupe_keys), so the
    # agent can see it stopped re-screening postings that return
    # created:false instead of silently getting a shorter feed.
    feed_already_screened: int = 0


class AgentConfigUpdate(_Camel):
    """Partial PUT /api/agent/config body — every field optional.

    Mirrors AnswersUpdate's merge semantics: omitted fields stay None and are
    excluded via `model_dump(exclude_unset=True)`, so the route only applies
    the fields the client actually sent.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=to_camel)

    mode: str | None = None
    blocked_companies: list[str] | None = None
    run_at: list[str] | None = None
    run_days: list[str] | None = None
    run_timezone: str | None = None
    profiles: list[JobProfileModel] | None = None
    job_boards: list[JobBoardModel] | None = None
    target_companies: list[str] | None = None
    cooldown_days: int | None = None
    cooldown_days_same_role: int | None = None
    cooldown_days_same_company: int | None = None
    max_applications_per_run: int | None = None
    max_posting_age_days: int | None = None
    dork_recency: str | None = None

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in AgentConfig.MODES:
            raise ValueError(f"Unknown mode '{v}'. Expected one of {', '.join(AgentConfig.MODES)}.")
        return v

    @field_validator("blocked_companies")
    @classmethod
    def _strip_and_drop_empties(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return [s.strip() for s in v if s.strip()]

    @field_validator("run_at")
    @classmethod
    def _validate_run_at(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if not v:
            raise ValueError("runAt must not be empty")
        for t in v:
            if not _RUN_AT_RE.match(t):
                raise ValueError(f"invalid time {t!r}, expected HH:MM")
        return v

    @field_validator("run_days")
    @classmethod
    def _validate_run_days(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if not v:
            raise ValueError("runDays must not be empty")
        deduped: list[str] = []
        for d in v:
            if d not in _RUN_DAYS:
                raise ValueError(f"invalid day {d!r}, expected one of {sorted(_RUN_DAYS)}")
            if d not in deduped:
                deduped.append(d)
        return deduped

    @field_validator("run_timezone")
    @classmethod
    def _validate_run_timezone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except Exception as exc:
            raise ValueError(f"invalid timezone {v!r}: {exc}") from exc
        return v

    @field_validator("target_companies", mode="before")
    @classmethod
    def _validate_target_companies(cls, v: list[str] | str | None) -> list[str] | None:
        if v is None:
            return v
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            return [s.strip() for s in v if isinstance(s, str) and s.strip()]
        return v

    @field_validator("cooldown_days", "cooldown_days_same_role", "cooldown_days_same_company")
    @classmethod
    def _validate_cooldown_days(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 0:
            raise ValueError("cooldown days must be >= 0 (0 disables the window)")
        return v

    @field_validator("max_applications_per_run")
    @classmethod
    def _validate_max_applications_per_run(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 1:
            raise ValueError("maxApplicationsPerRun must be >= 1")
        return v

    @field_validator("max_posting_age_days")
    @classmethod
    def _validate_max_posting_age_days(cls, v: int | None) -> int | None:
        """0 is meaningful here — it disables the window — so only negatives fail.

        The upper bound stops a typo ("3650") from reading as a deliberate
        choice to consider year-old postings.
        """
        if v is None:
            return v
        if v < 0:
            raise ValueError("maxPostingAgeDays must be >= 0 (0 disables the window)")
        if v > 365:
            raise ValueError("maxPostingAgeDays must be <= 365")
        return v

    @field_validator("dork_recency")
    @classmethod
    def _validate_dork_recency(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in DORK_RECENCIES:
            raise ValueError(f"dorkRecency must be one of {', '.join(DORK_RECENCIES)}")
        return v

    @field_validator("profiles")
    @classmethod
    def _validate_profiles(cls, v: list[JobProfileModel] | None) -> list[JobProfileModel] | None:
        if v is None:
            return v
        # Check for non-empty unique names and salary ordering
        names_seen = set()
        for profile in v:
            name = profile.name.strip()
            if not name:
                raise ValueError("profile name must not be empty")
            if name in names_seen:
                raise ValueError(f"duplicate profile name: {name!r}")
            names_seen.add(name)
            # Check salary ordering: floor <= ask_min <= ask_max
            if profile.salary_floor is not None and profile.salary_ask_min is not None:
                if profile.salary_floor > profile.salary_ask_min:
                    raise ValueError("salary_floor must be <= salary_ask_min")
            if profile.salary_ask_min is not None and profile.salary_ask_max is not None:
                if profile.salary_ask_min > profile.salary_ask_max:
                    raise ValueError("salary_ask_min must be <= salary_ask_max")
        return v


class AgentLlmCredentials(_Camel):
    """GET /api/agent/llm-credentials response: never logged, response-only egress.

    Serves credentials for any of the four connection cards (claude, codex,
    openrouter, ollama). `provider` names which card the credentials came
    from and `wire` names the API dialect the caller must speak
    ("anthropic-messages", "openai-chat-completions", or "openai-responses"),
    so a provider-agnostic caller can dispatch on the response alone instead
    of assuming Anthropic.
    """

    auth_type: str
    token: str
    model: str = ""
    # Set only for Anthropic-compatible third parties (OpenRouter). Empty means
    # the agent talks to Anthropic directly, as it always did.
    base_url: str = ""
    # The connections/catalog.py card key this credential came from.
    provider: str = ""
    # The wire dialect to speak: "anthropic-messages", "openai-chat-completions",
    # or "openai-responses" (ChatGPT subscription).
    wire: str = ""


class AgentLlmTokenRefresh(_Camel):
    """POST /api/agent/llm-token/refresh body: the token the caller saw rejected."""

    provider: Literal["claude", "codex"]
    rejected_token_sha256: str

    @field_validator("rejected_token_sha256")
    @classmethod
    def _sha_hex(cls, v: str) -> str:
        v = v.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", v):
            raise ValueError("must be 64 hex characters")
        return v


class AgentLlmTokenResult(_Camel):
    """POST /api/agent/llm-token/refresh response. Never logged."""

    token: str


class AgentStatus(_Camel):
    """GET /api/agent/status — forwarded from the supervisor.js control server."""

    running: bool
    # True between a cancel request and the run's exit. The operator's Cancel
    # button needs to distinguish "stopping" from "running", or a run that is
    # slow to tear down reads as a cancel that did nothing.
    cancelling: bool = False
    last_started_at: str | None = None
    last_finished_at: str | None = None
    last_exit_code: int | None = None
    # Whether the last run ended because it was cancelled rather than on its
    # own. Its non-zero exit code is expected in that case, so the UI must not
    # report it as a failure.
    last_cancelled: bool = False
    # The in-progress run's id (None once it finishes), and the most recent
    # run's id (retained after it ends). Both default to None so an older
    # supervisor image that doesn't send them does not fail this response.
    current_run_id: str | None = None
    last_run_id: str | None = None


class AgentRunResult(_Camel):
    """POST /api/agent/run — forwarded from the supervisor.js control server."""

    started: bool
    running: bool


class AgentCancelResult(_Camel):
    """POST /api/agent/cancel — forwarded from the supervisor.js control server.

    ``cancelled`` is False when there was nothing to cancel, or when a cancel
    was already under way; it is not an error, and ``running`` reports what the
    supervisor still had in progress at the moment it answered.
    """

    cancelled: bool
    running: bool


class AgentRunStart(_Camel):
    """POST /api/agent/runs/{run_id}/start body — host-side run accounting.

    Called by agent/supervisor.js before it spawns daily-apply.sh, so a run
    that dies before the model's first turn (provider error, precondition
    abort, MCP failure) still has a record. Distinct from the model's
    ``start_run`` MCP tool, which remains and becomes an idempotent join:
    whichever arrives first creates the record.
    """

    # What started this run: "scheduled", "manual" (Run now) or "startup"
    # (RUN_ONCE). The model's start_run could only ever guess this.
    trigger: str = ""
    apply_cap: int = 0


class AgentRunFinish(_Camel):
    """POST /api/agent/runs/{run_id}/finish body — host-side run accounting.

    Applied only while the record is still "running" (runs.store
    .finish_if_running), so the model's own ``finish_run`` — which names where
    the run actually stopped — is never overwritten by the supervisor's
    exit-code-derived summary.
    """

    status: str = "failed"
    stopped_reason: str = ""


class AgentRunAccountingResult(_Camel):
    """Response for both host-side run accounting routes.

    ``recorded`` is False when there was nothing to do — a finish against a
    record the model already closed, or against an id no run was started for.
    It is not an error: this accounting is best-effort by design and must never
    be able to fail a run.
    """

    recorded: bool
