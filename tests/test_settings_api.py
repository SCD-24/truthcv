"""Settings API: status, save (masking), keep-existing, test-connection."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.routes as routes
from api.main import app
from providers.fake import FakeProvider

FERNET_KEY = "h2oN5GQVeWVhciVjWNImtAmWFyPGlrWvDCq8vXuqfmo="


@pytest.fixture()
def client(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    return TestClient(app)


def test_get_settings_status_no_secrets(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    b = r.json()
    assert b["encryptionAvailable"] is True
    assert b["anthropicKeySet"] is False


def test_post_settings_saves_and_masks(client):
    r = client.post(
        "/api/settings",
        json={"activeProvider": "anthropic", "apiKey": "sk-ant-secret"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["anthropicKeySet"] is True
    assert "sk-ant-secret" not in r.text  # raw key never returned


def test_post_settings_empty_key_keeps_existing(client):
    client.post("/api/settings", json={"activeProvider": "anthropic", "apiKey": "sk-1"})
    r = client.post("/api/settings", json={"activeProvider": "anthropic", "apiKey": ""})
    assert r.json()["anthropicKeySet"] is True


def test_settings_disabled_without_key(data_dir, monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    c = TestClient(app)
    assert c.get("/api/settings").json()["encryptionAvailable"] is False
    r = c.post("/api/settings", json={"activeProvider": "anthropic", "apiKey": "x"})
    assert r.status_code == 400


def test_test_connection_ok(client, monkeypatch):
    monkeypatch.setattr(routes, "get_provider", lambda *a, **k: FakeProvider(completions=["ok"]))
    r = client.post(
        "/api/settings/test",
        json={"activeProvider": "anthropic", "apiKey": "sk-1"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
