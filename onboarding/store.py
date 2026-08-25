"""Persistence for onboarding.yaml against the ./data volume.

Tracks one-time, server-remembered first-run onboarding progress: when the
user last reviewed an uploaded CV and when they last saw the guided tour.
Holds no secrets, so unlike the secret store this is plain YAML.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from modelrouting import store as modelrouting
from truth.store import data_dir


def _state_path() -> Path:
    """Where onboarding.yaml lives, alongside truth.yaml."""
    return data_dir() / "onboarding.yaml"


@dataclass
class OnboardingState:
    """First-run onboarding progress. Both fields are ISO-8601 timestamps or None."""

    cv_reviewed_at: str | None = None
    tour_seen_at: str | None = None

    def to_dict(self) -> dict:
        """Plain-dict form for YAML serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: object) -> OnboardingState:
        """Build a state from a loaded dict, defaulting any missing/bad field."""
        if not isinstance(raw, dict):
            return cls()
        cv = raw.get("cv_reviewed_at")
        tour = raw.get("tour_seen_at")
        return cls(
            cv_reviewed_at=cv if isinstance(cv, str) else None,
            tour_seen_at=tour if isinstance(tour, str) else None,
        )


def load() -> OnboardingState:
    """Load onboarding state; defaults if the file is missing or unparseable."""
    p = _state_path()
    if not p.exists():
        return OnboardingState()
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return OnboardingState()
    return OnboardingState.from_dict(raw)


def save(state: OnboardingState) -> OnboardingState:
    """Write onboarding state to onboarding.yaml. Returns it."""
    p = _state_path()
    p.write_text(
        yaml.safe_dump(state.to_dict(), sort_keys=False),
        encoding="utf-8",
    )
    return state


def _now() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def mark_cv_reviewed(when: str | None = None) -> OnboardingState:
    """Record that the user reviewed an uploaded CV, defaulting to now."""
    state = load()
    state.cv_reviewed_at = when if when is not None else _now()
    return save(state)


def mark_tour_seen(when: str | None = None) -> OnboardingState:
    """Record that the user has seen the guided tour, defaulting to now."""
    state = load()
    state.tour_seen_at = when if when is not None else _now()
    return save(state)


def provider_ready() -> bool:
    """Whether a default LLM provider route is configured (derived, not persisted)."""
    return modelrouting.load().default is not None
