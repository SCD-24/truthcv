"""Wire models for settings, onboarding, answers and model routing."""

from __future__ import annotations

from pydantic import Field, field_validator

from .common import _Camel


class SettingsStatus(_Camel):
    encryption_available: bool
    active_provider: str
    model: str = ""
    anthropic_key_set: bool = False
    openai_key_set: bool = False
    ollama_host: str = ""


class SettingsUpdate(_Camel):
    active_provider: str
    api_key: str | None = None
    model: str | None = None
    ollama_host: str | None = None


class TestResult(_Camel):
    ok: bool
    detail: str = ""


class ModelInfo(_Camel):
    id: str
    label: str
    effort_levels: list[str] = Field(default_factory=list)


class ModelList(_Camel):
    models: list[ModelInfo] = []


class ProfileStatus(_Camel):
    has_profile: bool


class OnboardingState(_Camel):
    """GET/PUT /api/onboarding response: first-run onboarding progress."""

    provider_done: bool
    has_profile: bool
    cv_reviewed_at: str | None = None
    tour_seen_at: str | None = None
    complete: bool


class OnboardingUpdate(_Camel):
    """Partial PUT /api/onboarding body — only the sent fields are merged."""

    cv_reviewed_at: str | None = None
    tour_seen_at: str | None = None


class AnswersModel(_Camel):
    """Canonical ATS screening answers — GET/PUT /api/profile/answers wire shape.

    Mirrors every field of truth.answers.Answers (the runbook-transcribed
    canonical answers plus canonical_cv_asset_id) so GET/PUT round-trips the
    full record instead of silently dropping fields pydantic doesn't know
    about.
    """

    phone: str = ""
    work_authorisation: str = ""
    notice_period: str = ""
    location_preference: str = ""
    canonical_cv_asset_id: str | None = None
    name: str = ""
    email: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""
    requires_sponsorship: str = ""
    work_authorisation_note: str = ""
    authorized_non_german_country: str = ""
    languages: str = ""
    highest_relevant_degree: str = ""
    other_degree: str = ""
    cs_degree: str = ""
    gpa: str = ""
    gender: str = ""
    years_of_experience: str = ""
    current_role: str = ""
    how_did_you_hear: str = ""


class AnswersUpdate(_Camel):
    """Partial PUT /api/profile/answers body — every field optional.

    Mirrors AnswersModel field-for-field, but all fields default to None so
    the route can tell "the client didn't send this field" (stays None, and
    is excluded via `model_dump(exclude_unset=True)`) apart from "the client
    sent it" — including an explicit empty string, which IS applied. This is
    what lets PUT merge only the supplied fields onto the existing stored
    answers instead of clobbering everything else back to blank/default.
    """

    phone: str | None = None
    work_authorisation: str | None = None
    notice_period: str | None = None
    location_preference: str | None = None
    canonical_cv_asset_id: str | None = None
    name: str | None = None
    email: str | None = None
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None
    requires_sponsorship: str | None = None
    work_authorisation_note: str | None = None
    authorized_non_german_country: str | None = None
    languages: str | None = None
    highest_relevant_degree: str | None = None
    other_degree: str | None = None
    cs_degree: str | None = None
    gpa: str | None = None
    gender: str | None = None
    years_of_experience: str | None = None
    current_role: str | None = None
    how_did_you_hear: str | None = None


class RouteModel(_Camel):
    """A single connection + model pair, with an optional effort level."""

    connection: str
    model: str = ""
    effort: str = ""


class RoutingModel(_Camel):
    """GET /api/routing response: all routing assignments."""

    tasks: dict[str, RouteModel] = Field(default_factory=dict)
    agent: RouteModel | None = None
    default: RouteModel | None = None
    agent_stages: dict[str, RouteModel] = Field(default_factory=dict)


class RoutingUpdate(_Camel):
    """Partial PUT /api/routing body — every field optional.

    Mirrors the merge semantics: omitted fields stay None and are excluded
    via `model_dump(exclude_unset=True)`, so the route only applies the
    fields the client actually sent. Unlike other merge-PUT bodies in this
    file, a field sent explicitly as `null` is NOT the same as omitting it:
    `default`/`agent` sent as null clears that route, and a task entry sent
    as null removes that task's route — see put_routing in routes.py.
    """

    tasks: dict[str, RouteModel | None] | None = None
    agent: RouteModel | None = None
    default: RouteModel | None = None
    # Per-agent-stage routes; a null entry clears that stage. Unknown stage
    # names are rejected (422) rather than silently dropped.
    agent_stages: dict[str, RouteModel | None] | None = None

    @field_validator("agent_stages")
    @classmethod
    def _known_stages(cls, v):
        from truthcv.integrations.modelrouting.store import AGENT_STAGE_NAMES

        for name in v or {}:
            if name not in AGENT_STAGE_NAMES:
                raise ValueError(f"unknown agent stage: {name}")
        return v
