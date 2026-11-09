"""First-run onboarding state, lifted out of the route handlers.

``has_profile`` is looked up through ``truth.pdf`` and the store through the
``onboarding.store`` module object at call time, so patches on either work.
"""

from __future__ import annotations

import truth.pdf as _pdf
from onboarding import store as _store


def _compute() -> dict:
    """Build the current onboarding status from provider routing, the profile,
    and the persisted onboarding progress."""
    provider_done = _store.provider_ready()
    profile_done = _pdf.has_profile()
    state = _store.load()
    return {
        "provider_done": provider_done,
        "has_profile": profile_done,
        "cv_reviewed_at": state.cv_reviewed_at,
        "tour_seen_at": state.tour_seen_at,
        "complete": provider_done and profile_done and state.cv_reviewed_at is not None,
    }


def get_state() -> dict:
    """First-run onboarding progress: provider setup, profile, CV review, tour."""
    _store.ensure_initialized()
    return _compute()


def update_state(sent: dict) -> dict:
    """Merge only the fields the client actually sent onto the stored state,
    then return the recomputed status."""
    _store.ensure_initialized()
    merged = _store.load().to_dict()
    merged.update(sent)
    _store.save(_store.OnboardingState.from_dict(merged))
    return _compute()
