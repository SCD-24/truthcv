"""Job Screening store: atomic persistence, fail-safe corrupt load, verdict
round trips, and cooldown derivation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import applications
from screening.cooldown import cooldown
from screening.model import VERDICT_VALUES
from screening.store import create, load_all, screenings_path


def test_empty_when_no_file(data_dir):
    assert load_all() == []


def test_atomic_write_leaves_no_tmp(data_dir):
    create({"company": "Acme", "verdict": "passed"})
    tmp = screenings_path().with_suffix(".json.tmp")
    assert not tmp.exists()


def test_load_empty_on_corrupt_json(data_dir):
    screenings_path().write_text("{not valid json", encoding="utf-8")
    assert load_all() == []


def test_load_empty_when_top_level_not_a_list(data_dir):
    screenings_path().write_text(json.dumps({"oops": True}), encoding="utf-8")
    assert load_all() == []


@pytest.mark.parametrize("verdict", VERDICT_VALUES)
def test_verdict_round_trips(data_dir, verdict):
    created = create(
        {"company": "Acme", "role": "Engineer", "verdict": verdict}
    )
    assert created.verdict == verdict

    reloaded = load_all()
    assert len(reloaded) == 1
    assert reloaded[0].verdict == verdict


def test_cooldown_from_screening_alone(data_dir):
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    create(
        {
            "company": "Acme",
            "role": "Engineer",
            "verdict": "rejected",
            "cooldown_expires": future,
        }
    )
    status = cooldown("Acme", "Engineer")
    assert status.in_cooldown is True
    assert status.expires == future


def test_cooldown_from_application_alone(data_dir, monkeypatch):
    monkeypatch.setenv("APPLICATION_COOLDOWN_DAYS", "90")
    recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).date()
    applications.create(
        {
            "company": "Acme",
            "role": "Engineer",
            "application_date": recent_date.isoformat(),
        }
    )
    status = cooldown("Acme", "Engineer")
    assert status.in_cooldown is True

    expected_expiry = (
        datetime(recent_date.year, recent_date.month, recent_date.day, tzinfo=timezone.utc)
        + timedelta(days=90)
    )
    assert datetime.fromisoformat(status.expires) == expected_expiry


def test_cooldown_prefers_later_of_both_sources(data_dir, monkeypatch):
    monkeypatch.setenv("APPLICATION_COOLDOWN_DAYS", "90")

    # Screening's own cooldown expires soon (near future).
    near = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    create(
        {
            "company": "Acme",
            "role": "Engineer",
            "verdict": "rejected",
            "cooldown_expires": near,
        }
    )

    # Application-derived expiry (application_date + 90 days) lands further out.
    app_date = (datetime.now(timezone.utc) - timedelta(days=10)).date()
    applications.create(
        {
            "company": "Acme",
            "role": "Engineer",
            "application_date": app_date.isoformat(),
        }
    )
    expected_far_expiry = (
        datetime(app_date.year, app_date.month, app_date.day, tzinfo=timezone.utc)
        + timedelta(days=90)
    )

    status = cooldown("Acme", "Engineer")
    assert status.in_cooldown is True
    assert datetime.fromisoformat(status.expires) == expected_far_expiry
    assert datetime.fromisoformat(status.expires) > datetime.fromisoformat(near)


def test_cooldown_expired_reports_not_in_cooldown(data_dir):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    create(
        {
            "company": "Acme",
            "role": "Engineer",
            "verdict": "rejected",
            "cooldown_expires": past,
        }
    )
    status = cooldown("Acme", "Engineer")
    assert status.in_cooldown is False
    assert status.expires == past


def test_cooldown_matches_case_and_whitespace_insensitively(data_dir):
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    create(
        {
            "company": "  Acme Corp  ",
            "role": " Engineer ",
            "verdict": "rejected",
            "cooldown_expires": future,
        }
    )
    status = cooldown("ACME CORP", "engineer")
    assert status.in_cooldown is True
    assert status.expires == future
