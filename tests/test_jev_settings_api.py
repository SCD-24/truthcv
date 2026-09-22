"""Jev settings API: GET status, PUT key/toggle, clear key, test route.

Patterned on tests/test_settings_api.py and the job-board-key routes in
tests/test_job_board_feed_api.py. The HTTP layer is always mocked — no live
network call is made.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import secretstore
from api.main import app
from screening import jev

FERNET_KEY = "h2oN5GQVeWVhciVjWNImtAmWFyPGlrWvDCq8vXuqfmo="


@pytest.fixture()
def client(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    return TestClient(app)


def test_get_status_starts_unset(client):
    r = client.get("/api/settings/jev")
    assert r.status_code == 200
    body = r.json()
    assert body["keySet"] is False
    assert body["useForScreening"] is False
    assert body["encryptionAvailable"] is True


def test_put_key_and_toggle(client):
    r = client.put("/api/settings/jev", json={"apiKey": "jev_secret", "useForScreening": True})
    assert r.status_code == 200
    body = r.json()
    assert body["keySet"] is True
    assert body["useForScreening"] is True
    assert "jev_secret" not in r.text

    got = client.get("/api/settings/jev").json()
    assert got["keySet"] is True
    assert got["useForScreening"] is True
    assert secretstore.get_connection("jev")["apiKey"] == "jev_secret"


def test_put_empty_key_clears_it(client):
    client.put("/api/settings/jev", json={"apiKey": "jev_secret"})
    r = client.put("/api/settings/jev", json={"apiKey": ""})
    assert r.json()["keySet"] is False
    assert secretstore.get_connection("jev").get("apiKey") in (None, "")


def test_put_toggle_only_leaves_key_untouched(client):
    client.put("/api/settings/jev", json={"apiKey": "jev_secret"})
    r = client.put("/api/settings/jev", json={"useForScreening": True})
    assert r.json()["keySet"] is True
    assert r.json()["useForScreening"] is True


def test_the_key_is_never_returned_by_any_route(client):
    client.put("/api/settings/jev", json={"apiKey": "jev_super_secret"})
    for path in ("/api/settings/jev",):
        assert "jev_super_secret" not in client.get(path).text


def test_put_key_requires_encryption(data_dir, monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    c = TestClient(app)
    r = c.put("/api/settings/jev", json={"apiKey": "jev_secret"})
    assert r.status_code == 400


def test_put_toggle_only_also_requires_encryption(data_dir, monkeypatch):
    """useForScreening is written through the same encrypted store as the
    key, so it needs ENCRYPTION_KEY too, not just a 200 with nothing saved."""
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    c = TestClient(app)
    r = c.put("/api/settings/jev", json={"useForScreening": True})
    assert r.status_code == 400


def test_test_route_uses_mocked_check_key(client, monkeypatch):
    monkeypatch.setattr(jev, "check_key", lambda key: (True, "Jev accepted the key."))
    client.put("/api/settings/jev", json={"apiKey": "jev_secret"})
    r = client.post("/api/settings/jev/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["detail"] == "Jev accepted the key."


def test_test_route_reports_failure_from_check_key(client, monkeypatch):
    monkeypatch.setattr(jev, "check_key", lambda key: (False, "Jev rejected the key."))
    r = client.post("/api/settings/jev/test")
    assert r.json()["ok"] is False
