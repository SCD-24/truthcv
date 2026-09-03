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


def test_put_empty_connection_400(client):
    resp = client.put("/api/routing", json={"default": {"connection": ""}})
    assert resp.status_code == 400
    # Verify nothing was saved
    assert client.get("/api/routing").json()["default"] is None


def test_put_null_default_clears_it(client):
    client.put("/api/routing", json={"default": {"connection": "claude", "model": "m1"}})
    resp = client.put("/api/routing", json={"default": None})
    assert resp.status_code == 200
    assert resp.json()["default"] is None
    assert client.get("/api/routing").json()["default"] is None


def test_put_null_task_entry_removes_it(client):
    client.put("/api/routing", json={"tasks": {"keywords": {"connection": "ollama", "model": "llama3.1"}}})
    resp = client.put("/api/routing", json={"tasks": {"keywords": None}})
    assert resp.status_code == 200
    assert "keywords" not in resp.json()["tasks"]
    assert "keywords" not in client.get("/api/routing").json()["tasks"]


def test_put_null_task_entry_leaves_other_tasks_untouched(client):
    client.put(
        "/api/routing",
        json={
            "tasks": {
                "keywords": {"connection": "ollama", "model": "llama3.1"},
                "tailor": {"connection": "claude", "model": "m1"},
            }
        },
    )
    client.put("/api/routing", json={"tasks": {"keywords": None}})
    body = client.get("/api/routing").json()
    assert "keywords" not in body["tasks"]
    assert body["tasks"]["tailor"]["connection"] == "claude"


def test_put_absent_default_leaves_it_untouched(client):
    client.put("/api/routing", json={"default": {"connection": "claude", "model": "m1"}})
    client.put("/api/routing", json={"agent": {"connection": "codex", "model": "gpt-x"}})
    body = client.get("/api/routing").json()
    assert body["default"]["connection"] == "claude"
    assert body["agent"]["connection"] == "codex"


def test_put_agent_context_window_roundtrips(client):
    resp = client.put(
        "/api/routing",
        json={"agent": {"connection": "claude", "model": "m1", "contextWindow": 200000}},
    )
    assert resp.status_code == 200
    assert resp.json()["agent"]["contextWindow"] == 200000
    body = client.get("/api/routing").json()
    assert body["agent"]["contextWindow"] == 200000


def test_put_context_window_below_minimum_400(client):
    resp = client.put(
        "/api/routing",
        json={"agent": {"connection": "claude", "model": "m1", "contextWindow": 4096}},
    )
    assert resp.status_code == 400


def test_put_context_window_negative_400(client):
    resp = client.put(
        "/api/routing",
        json={"agent": {"connection": "claude", "model": "m1", "contextWindow": -1}},
    )
    assert resp.status_code == 400
