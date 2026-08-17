import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def test_get_empty_routing(client):
    body = client.get("/api/routing").json()
    assert body == {"tasks": {}, "agent": None, "default": None}


def test_put_partial_update_merges(client):
    client.put("/api/routing", json={"default": {"connection": "claude", "model": "m1"}})
    client.put("/api/routing", json={"tasks": {"keywords": {"connection": "ollama", "model": "llama3.1"}}})
    body = client.get("/api/routing").json()
    assert body["default"]["connection"] == "claude"          # survived second PUT
    assert body["tasks"]["keywords"]["model"] == "llama3.1"


def test_put_unknown_connection_400(client):
    resp = client.put("/api/routing", json={"default": {"connection": "copilot"}})
    assert resp.status_code == 400


def test_put_unknown_task_ignored(client):
    client.put("/api/routing", json={"tasks": {"nonsense": {"connection": "claude"}}})
    assert client.get("/api/routing").json()["tasks"] == {}
