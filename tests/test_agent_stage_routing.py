import json

import pytest
from fastapi.testclient import TestClient

import modelrouting
from api import routes
from api.main import app
from api.schemas import AgentLlmCredentials
from modelrouting.store import routing_path


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def test_legacy_file_without_agent_stages_loads(data_dir):
    routing_path().write_text(json.dumps({"agent": {"connection": "claude", "model": "m"}}))
    r = modelrouting.load()
    assert r.agent_stages == {}
    assert r.agent.model == "m"


def test_round_trip_and_unknown_stage_dropped(data_dir):
    r = modelrouting.Routing(
        agent_stages={"screening": modelrouting.Route("ollama", "llama")}
    )
    modelrouting.save(r)
    raw = json.loads(routing_path().read_text())
    raw["agent_stages"]["bogus"] = {"connection": "claude"}
    routing_path().write_text(json.dumps(raw))
    loaded = modelrouting.load()
    assert set(loaded.agent_stages) == {"screening"}
    assert loaded.agent_stages["screening"].model == "llama"


def test_resolve_falls_back_to_agent(data_dir):
    r = modelrouting.Routing(
        agent=modelrouting.Route("claude", "a"),
        agent_stages={"screening": modelrouting.Route("ollama", "s")},
    )
    assert modelrouting.resolve_agent_stage(r, "screening").model == "s"
    assert modelrouting.resolve_agent_stage(r, "extract").model == "a"
    assert modelrouting.resolve_agent_stage(modelrouting.Routing(), "extract") is None


def test_put_get_and_clear_stage(client):
    resp = client.put(
        "/api/routing",
        json={"agentStages": {"screening": {"connection": "ollama", "model": "x"}}},
    )
    assert resp.status_code == 200
    assert resp.json()["agentStages"]["screening"]["model"] == "x"
    assert client.get("/api/routing").json()["agentStages"]["screening"]["model"] == "x"
    client.put("/api/routing", json={"agentStages": {"screening": None}})
    assert client.get("/api/routing").json()["agentStages"] == {}


def test_put_unknown_stage_422(client):
    resp = client.put(
        "/api/routing", json={"agentStages": {"nope": {"connection": "claude"}}}
    )
    assert resp.status_code == 422


def test_llm_routes_404_without_token(client, monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "secret")
    assert client.get("/api/agent/llm-routes").status_code == 404
    assert (
        client.get("/api/agent/llm-routes", headers={"X-Agent-Token": "bad"}).status_code
        == 404
    )


def test_llm_routes_shape(client, monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "secret")

    def fake(model):
        return AgentLlmCredentials(
            auth_type="url", token="", model=model, base_url="http://o",
            provider="ollama", wire="openai-chat-completions",
        )

    monkeypatch.setitem(routes._CARD_CREDENTIALS, "ollama", fake)
    empty = client.get("/api/agent/llm-routes", headers={"X-Agent-Token": "secret"})
    assert empty.status_code == 200
    assert empty.json() == {"stages": {"apply": None, "screening": None, "extract": None}}

    modelrouting.save(
        modelrouting.Routing(
            agent_stages={"screening": modelrouting.Route("ollama", "small")}
        )
    )
    stages = client.get(
        "/api/agent/llm-routes", headers={"X-Agent-Token": "secret"}
    ).json()["stages"]
    assert stages["apply"] is None
    assert stages["extract"] is None
    assert stages["screening"]["model"] == "small"
    assert stages["screening"]["provider"] == "ollama"
