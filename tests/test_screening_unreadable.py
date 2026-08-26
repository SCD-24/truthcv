"""A posting the agent could not read is recorded with a blocker, not a
guessed verdict — screening/model.py + screening/store.py + the wire model."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from screening import store
from screening.model import validate_verdict


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def test_blocked_record_round_trips_with_pending_approval(data_dir):
    s = store.create(
        {
            "company": "Acme",
            "role": "Dev",
            "url": "https://acme.example/jobs/1",
            "screening_blocker": "unreadable",
        }
    )
    assert s.screening_blocker == "unreadable"
    assert s.verdict == ""
    assert s.approval == "pending"


def test_login_required_blocker_still_queues_for_approval(data_dir):
    """The operator can sign in themselves, so this stays actionable."""
    s = store.create(
        {
            "company": "Acme",
            "role": "Dev",
            "url": "https://acme.example/jobs/9",
            "screening_blocker": "login_required",
        }
    )
    assert s.screening_blocker == "login_required"
    assert s.approval == "pending"


def test_unknown_blocker_value_raises(data_dir):
    with pytest.raises(ValueError):
        store.create(
            {
                "company": "Acme",
                "role": "Dev",
                "url": "https://acme.example/jobs/2",
                "screening_blocker": "bogus",
            }
        )


def test_verdict_and_blocker_both_empty_still_raises():
    with pytest.raises(ValueError):
        validate_verdict("", blocker="")


def test_verdict_empty_with_blocker_is_accepted():
    assert validate_verdict("", blocker="unreadable") == ""


def test_blocked_record_absent_from_signin_queue(client):
    store.create(
        {
            "company": "Acme",
            "role": "Dev",
            "url": "https://acme.example/jobs/3",
            "screening_blocker": "login_required",
        }
    )
    r = client.get("/api/browser/signin-queue")
    assert r.status_code == 200
    assert r.json()["sites"] == []


def test_screening_blocker_appears_in_get_screenings(client):
    store.create(
        {
            "company": "Acme",
            "role": "Dev",
            "url": "https://acme.example/jobs/4",
            "screening_blocker": "expired",
        }
    )
    r = client.get("/api/screenings")
    assert r.status_code == 200
    records = r.json()
    assert any(
        rec.get("screeningBlocker") == "expired" or rec.get("screening_blocker") == "expired"
        for rec in records
    )


def test_not_found_blocker_is_not_queued_for_approval(data_dir):
    """There is no decision to make and nothing to draft from a dead posting."""
    s = store.create(
        {
            "company": "Acme",
            "role": "Dev",
            "url": "https://acme.example/jobs/5",
            "screening_blocker": "not_found",
        }
    )
    assert s.screening_blocker == "not_found"
    assert s.approval == ""


def test_expired_blocker_is_not_queued_for_approval(data_dir):
    s = store.create(
        {
            "company": "Acme",
            "role": "Dev",
            "url": "https://acme.example/jobs/6",
            "screening_blocker": "expired",
        }
    )
    assert s.screening_blocker == "expired"
    assert s.approval == ""


def test_not_found_and_expired_absent_from_pending_listing(client):
    store.create(
        {
            "company": "Acme",
            "role": "Dev",
            "url": "https://acme.example/jobs/7",
            "screening_blocker": "not_found",
        }
    )
    store.create(
        {
            "company": "Acme",
            "role": "Dev",
            "url": "https://acme.example/jobs/8",
            "screening_blocker": "expired",
        }
    )
    r = client.get("/api/screenings", params={"approval": "pending"})
    assert r.status_code == 200
    records = r.json()
    assert not any(
        rec.get("screeningBlocker") in ("not_found", "expired")
        or rec.get("screening_blocker") in ("not_found", "expired")
        for rec in records
    )
