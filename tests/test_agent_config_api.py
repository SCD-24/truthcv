"""/api/agent/config: defaults, merge-on-PUT, validation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def test_get_returns_defaults(client, data_dir):
    r = client.get("/api/agent/config")
    assert r.status_code == 200
    assert r.json() == {
        "enabled": True,
        "blockedCompanies": [],
        "runAt": ["09:00", "15:00"],
        "runDays": ["mon", "tue", "wed", "thu", "fri"],
    }


def test_put_merges_partial(client, data_dir):
    r = client.put("/api/agent/config", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["runAt"] == ["09:00", "15:00"]  # untouched


def test_put_blocklist_strips_and_drops_empties(client, data_dir):
    r = client.put("/api/agent/config", json={"blockedCompanies": [" Acme ", "", "  "]})
    assert r.json()["blockedCompanies"] == ["Acme"]


def test_put_rejects_bad_time(client, data_dir):
    assert client.put("/api/agent/config", json={"runAt": ["9:00"]}).status_code == 422
    assert client.put("/api/agent/config", json={"runAt": ["25:00"]}).status_code == 422
    assert client.put("/api/agent/config", json={"runAt": []}).status_code == 422


def test_put_rejects_bad_day(client, data_dir):
    assert client.put("/api/agent/config", json={"runDays": ["monday"]}).status_code == 422
    assert client.put("/api/agent/config", json={"runDays": []}).status_code == 422
