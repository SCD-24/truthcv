"""Wire models for job profiles, job boards, feeds and search queries."""

from __future__ import annotations

from pydantic import ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from agentconfig.boards import posting_url_pattern_error, search_url_error

from .common import _Camel


class JobProfileModel(_Camel):
    """Job search profile with search criteria and requirements."""

    name: str = ""
    enabled: bool = True
    keywords: list[str] = Field(default_factory=list)
    title_keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_model: str | None = None
    employment_country: str | None = None
    eor_allowed: bool | None = None
    require_entity_verification: bool = True
    salary_floor: int | None = None
    salary_ask_min: int | None = None
    salary_ask_max: int | None = None
    # User-chosen currency code; None means the user has not configured one
    # and no default currency may be assumed.
    currency: str | None = None
    working_language: str | None = None
    glassdoor_min: float | None = None
    glassdoor_min_reviews: int | None = None
    accepted_role_types: list[str] = Field(default_factory=list)
    rejected_role_types: list[str] = Field(default_factory=list)

    @field_validator("salary_floor", "salary_ask_min", "salary_ask_max")
    @classmethod
    def _validate_salary_values(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("salary values must be > 0")
        return v

    @field_validator("glassdoor_min")
    @classmethod
    def _validate_glassdoor_min(cls, v: float | None) -> float | None:
        if v is not None and (v < 0 or v > 5):
            raise ValueError("glassdoor_min must be between 0 and 5")
        return v

    @field_validator("glassdoor_min_reviews")
    @classmethod
    def _validate_glassdoor_min_reviews(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("glassdoor_min_reviews must be >= 0")
        return v

    @field_validator("keywords", "title_keywords", "locations", "accepted_role_types", "rejected_role_types", mode="before")
    @classmethod
    def _split_comma_delimited_lists(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            return [s.strip() for s in v if isinstance(s, str) and s.strip()]
        return v


class JobBoardModel(_Camel):
    """One job board the agent searches AND a site the operator signs in to.

    ``source``/``signin_url``/``mode`` are the operator's stored input —
    ``mode`` ("dork" or "direct") is only ever actually settable when the
    board is custom; a board dict that omits it (an older client, or a
    catalog board) still validates. ``domain``, ``effective_signin_url``,
    ``is_default``, ``is_api``, ``key_required`` and ``mode_locked`` are
    response-only, resolved server-side by the routes from agentconfig/boards.py
    and stripped on a PUT — ``is_default`` marks a board that is built-in and
    cannot be removed (but CAN be disabled, via ``enabled``), ``is_api`` a board
    reached via an HTTP API rather than a browser sign-in
    (``effective_signin_url`` is always "" for those), ``key_required`` whether
    that API board needs a saved key before its feed can run (false for a public
    API board like Arbeitnow, and for every non-API board), and ``mode_locked``
    marks a catalog board whose ``mode`` is fixed and not operator-editable.

    ``enabled`` IS operator-settable, for every board including a default —
    a disabled board stays listed (re-enableable) but drops out of
    discovery, dorks, direct boards, and API feeds.
    """

    source: str = ""
    signin_url: str = ""
    mode: str = ""
    search_url: str = ""
    enabled: bool = True
    posting_url_pattern: str = ""
    mode_locked: bool = False
    domain: str = ""
    effective_signin_url: str = ""
    is_default: bool = False
    is_api: bool = False
    key_required: bool = False

    @field_validator("search_url")
    @classmethod
    def _validate_search_url(cls, v: str) -> str:
        """Empty is fine (no search-results template configured); otherwise it
        must be an http(s) URL carrying a ``{keywords}`` placeholder and no
        placeholder other than ``{keywords}``/``{location}``.
        """
        err = search_url_error(v)
        if err:
            raise ValueError(err)
        return v

    @field_validator("posting_url_pattern")
    @classmethod
    def _validate_posting_url_pattern(cls, v: str) -> str:
        """Empty is fine (no posting-link glob configured); otherwise it must
        be an http(s) URL glob with a valid host and no whitespace/braces.
        """
        err = posting_url_pattern_error(v)
        if err:
            raise ValueError(err)
        return v


class DirectBoardProfileModel(_Camel):
    """One enabled, keyword-bearing profile's search criteria for a direct board (response-only)."""

    profile: str = ""
    keywords: list[str] = Field(default_factory=list)
    title_keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    rejected_role_types: list[str] = Field(default_factory=list)
    remote_model: str | None = None


class DirectBoardModel(_Camel):
    """One direct-mode job board: searched on-site by the agent, not via a Google dork (response-only)."""

    url: str = ""
    signin_url: str = ""
    search_url: str = ""
    posting_url_pattern: str = ""
    profiles: list[DirectBoardProfileModel] = Field(default_factory=list)


class FeedPostingModel(_Camel):
    """One posting pulled from an API-backed board (response-only)."""

    profile: str = ""
    source: str = ""
    title: str = ""
    company: str = ""
    url: str = ""
    employment_type: str = ""
    salary_range: str = ""
    posted_at: str = ""
    tier: str = "api"


class JobBoardKeyStatus(_Camel):
    """Whether an API-backed board has a key saved — never the key itself."""

    source: str
    key_set: bool = False
    encryption_available: bool = True


class JobBoardKeyUpdate(_Camel):
    """PUT body for an API-backed board's key. An empty string clears it."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=to_camel)

    api_key: str


class JevSettingsStatus(_Camel):
    """Jev cross-check settings — never returns the key itself."""

    key_set: bool = False
    use_for_screening: bool = False
    use_for_email_tracking: bool = False
    encryption_available: bool = True


class JevSettingsUpdate(_Camel):
    """PUT body for Jev settings. An empty ``api_key`` string clears it;
    omitting a field leaves it unchanged."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=to_camel)

    api_key: str | None = None
    use_for_screening: bool | None = None
    use_for_email_tracking: bool | None = None


class CompanyBoardModel(_Camel):
    """Resolved company board entry (response-only)."""

    company: str
    careers_url: str
    ats: str = ""
    status: str = "ok"
    resolved_at: str = ""


class SearchQueryModel(_Camel):
    """Composed search query (response-only)."""

    profile: str
    # Every profile that composed this (deduplicated) URL; profile is the first.
    profiles: list[str] = []
    source: str
    query: str
    url: str
