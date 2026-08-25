"""Tests for onboarding/store.py."""

from __future__ import annotations

from onboarding import store as onboarding_store
from truth import store as truth_store
from truth.model import Skill, Truth


def test_load_defaults_when_no_file(data_dir):
    state = onboarding_store.load()
    assert state.cv_reviewed_at is None
    assert state.tour_seen_at is None


def test_mark_cv_reviewed_round_trips(data_dir):
    onboarding_store.mark_cv_reviewed("2024-01-01T00:00:00+00:00")
    state = onboarding_store.load()
    assert state.cv_reviewed_at == "2024-01-01T00:00:00+00:00"


def test_mark_tour_seen_does_not_clobber_cv_reviewed(data_dir):
    onboarding_store.mark_cv_reviewed("2024-01-01T00:00:00+00:00")
    onboarding_store.mark_tour_seen("2024-02-01T00:00:00+00:00")
    state = onboarding_store.load()
    assert state.cv_reviewed_at == "2024-01-01T00:00:00+00:00"
    assert state.tour_seen_at == "2024-02-01T00:00:00+00:00"


def test_mark_cv_reviewed_does_not_clobber_tour_seen(data_dir):
    onboarding_store.mark_tour_seen("2024-02-01T00:00:00+00:00")
    onboarding_store.mark_cv_reviewed("2024-01-01T00:00:00+00:00")
    state = onboarding_store.load()
    assert state.tour_seen_at == "2024-02-01T00:00:00+00:00"
    assert state.cv_reviewed_at == "2024-01-01T00:00:00+00:00"


def test_corrupt_file_loads_as_defaults(data_dir):
    path = data_dir / "onboarding.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    state = onboarding_store.load()
    assert state.cv_reviewed_at is None
    assert state.tour_seen_at is None


def test_provider_ready_false_when_no_default(data_dir, monkeypatch):
    class Routing:
        default = None

    monkeypatch.setattr(onboarding_store.modelrouting, "load", lambda: Routing())
    assert onboarding_store.provider_ready() is False


def test_provider_ready_true_when_default_set(data_dir, monkeypatch):
    class Routing:
        default = object()

    monkeypatch.setattr(onboarding_store.modelrouting, "load", lambda: Routing())
    assert onboarding_store.provider_ready() is True


def test_ensure_initialized_writes_defaults_for_empty_data_dir(data_dir):
    state = onboarding_store.ensure_initialized()
    assert state.cv_reviewed_at is None
    assert state.tour_seen_at is None
    assert (data_dir / "onboarding.yaml").exists()


def test_ensure_initialized_backfills_when_truth_has_content(data_dir):
    truth_store.save(
        Truth(skills=[Skill(id="s1", value="Python", source="user-confirmed")])
    )
    state = onboarding_store.ensure_initialized()
    assert state.cv_reviewed_at is not None


def test_ensure_initialized_is_idempotent_no_late_backfill(data_dir):
    first = onboarding_store.ensure_initialized()
    assert first.cv_reviewed_at is None

    truth_store.save(
        Truth(skills=[Skill(id="s1", value="Python", source="user-confirmed")])
    )
    second = onboarding_store.ensure_initialized()
    assert second.cv_reviewed_at is None
