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
from truth import store as truth_store
from storage import data_dir


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


def has_existing_cv() -> bool:
    """Whether truth.yaml already holds real CV content.

    Used only to backfill pre-existing users on their first onboarding read;
    a ValueError from a corrupt truth.yaml is treated as 'no existing CV'.
    """
    try:
        truth = truth_store.load()
    except ValueError:
        return False
    has_header = bool(truth.profile.name or truth.profile.summary)
    return bool(truth.experiences or truth.education or truth.skills or truth.hobbies or has_header)


def ensure_initialized() -> OnboardingState:
    """Create onboarding.yaml on first read, backfilling pre-existing users.

    If onboarding.yaml already exists, this is a no-op that just loads it.
    Otherwise it writes the file so this backfill can never fire again: a
    user who already had a CV before onboarding existed gets cv_reviewed_at
    set to now; a genuinely new user gets both fields left None.
    """
    if _state_path().exists():
        return load()
    state = OnboardingState(cv_reviewed_at=_now() if has_existing_cv() else None)
    return save(state)
