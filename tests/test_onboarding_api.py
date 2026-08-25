"""Tests for GET/PUT /api/onboarding, and that /api/profile is untouched."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.routes as routes
from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def test_get_onboarding_fresh_data_dir(client):
    body = client.get("/api/onboarding").json()
    assert body == {
        "providerDone": False,
        "hasProfile": False,
        "cvReviewedAt": None,
        "tourSeenAt": None,
        "complete": False,
    }


def test_put_cv_reviewed_persists(client):
    client.put("/api/onboarding", json={"cvReviewedAt": "2024-01-01T00:00:00+00:00"})
    body = client.get("/api/onboarding").json()
    assert body["cvReviewedAt"] == "2024-01-01T00:00:00+00:00"


def test_put_tour_seen_does_not_clear_cv_reviewed(client):
    client.put("/api/onboarding", json={"cvReviewedAt": "2024-01-01T00:00:00+00:00"})
    r = client.put("/api/onboarding", json={"tourSeenAt": "2024-02-01T00:00:00+00:00"})
    body = r.json()
    assert body["cvReviewedAt"] == "2024-01-01T00:00:00+00:00"
    assert body["tourSeenAt"] == "2024-02-01T00:00:00+00:00"


def test_complete_requires_provider_profile_and_cv_reviewed(client, monkeypatch):
    monkeypatch.setattr(routes.onboarding_store, "provider_ready", lambda: True)
    monkeypatch.setattr(routes, "has_profile", lambda: True)
    assert client.get("/api/onboarding").json()["complete"] is False

    client.put("/api/onboarding", json={"cvReviewedAt": "2024-01-01T00:00:00+00:00"})
    assert client.get("/api/onboarding").json()["complete"] is True


def test_profile_endpoint_shape_unchanged(client):
    assert client.get("/api/profile").json() == {"hasProfile": False}
