"""Settings API: status, save (masking), keep-existing, test-connection.

Legacy /api/settings is a deprecation shim over the v2 connection store
(secretstore.get_connection / modelrouting) — these tests assert both the
preserved v1 wire shape and that the shim actually reads/writes v2 state.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.routes as routes
import modelrouting
import secretstore
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


def test_post_settings_writes_v2_connection_and_routing_default(client):
    """Old single-provider POST shape is a shim: the key lands in the v2
    connection store and the routing default points at the mapped card."""
    r = client.post(
        "/api/settings",
        json={"activeProvider": "anthropic", "apiKey": "sk-ant-secret", "model": "claude-x"},
    )
    assert r.status_code == 200
    assert secretstore.get_connection("claude")["apiKey"] == "sk-ant-secret"
    routing = modelrouting.load()
    assert routing.default == modelrouting.Route("claude", "claude-x")


def test_post_settings_openai_maps_to_codex_connection(client):
    r = client.post(
        "/api/settings",
        json={"activeProvider": "openai", "apiKey": "sk-oa-secret"},
    )
    assert r.status_code == 200
    assert secretstore.get_connection("codex")["apiKey"] == "sk-oa-secret"
    assert modelrouting.load().default.connection == "codex"


def test_post_settings_ollama_maps_host_to_base_url(client):
    r = client.post(
        "/api/settings",
        json={"activeProvider": "ollama", "ollamaHost": "http://box:11434"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["ollamaHost"] == "http://box:11434"
    assert secretstore.get_connection("ollama")["baseUrl"] == "http://box:11434"


def test_get_settings_reflects_v2_store_directly(client):
    """GET derives its wire shape from v2 state written outside the shim."""
    secretstore.set_connection("claude", {"apiKey": "sk-direct"})
    modelrouting.save(modelrouting.Routing(default=modelrouting.Route("claude", "claude-direct")))
    b = client.get("/api/settings").json()
    assert b["activeProvider"] == "anthropic"
    assert b["model"] == "claude-direct"
    assert b["anthropicKeySet"] is True
    assert "sk-direct" not in client.get("/api/settings").text


def test_get_settings_falls_back_to_legacy_default_without_routing(client):
    """No routing.default saved: GET falls back to secretstore.legacy_default()."""
    secretstore.set_connection("codex", {"apiKey": "sk-legacy"})
    store = secretstore.load_store()
    store["legacyDefault"] = {"provider": "openai", "model": "gpt-legacy"}
    secretstore.save_store(store)
    assert modelrouting.load().default is None
    b = client.get("/api/settings").json()
    assert b["activeProvider"] == "openai"
    assert b["model"] == "gpt-legacy"
    assert b["openaiKeySet"] is True


def test_post_settings_unknown_provider_400_writes_nothing(client):
    """An active_provider that maps to no known card must 400, not silently
    create a connection or a dangling routing default for a card that isn't
    in the catalog."""
    r = client.post(
        "/api/settings",
        json={"activeProvider": "copilot", "apiKey": "sk-x"},
    )
    assert r.status_code == 400
    assert "copilot" not in secretstore.load_store().get("connections", {})
    assert modelrouting.load().default is None


def test_models_uses_typed_unsaved_key(client, monkeypatch):
    """/api/models constructs a provider directly from a submitted-but-unsaved
    key, per _provider_from_update, without persisting it."""
    import providers.anthropic_provider as ap

    captured: dict = {}

    def fake_init(self, model=None, api_key=None, oauth=False):
        captured["api_key"] = api_key

    monkeypatch.setattr(ap.AnthropicProvider, "__init__", fake_init)
    monkeypatch.setattr(ap.AnthropicProvider, "list_models", lambda self: [{"id": "claude-x"}])

    r = client.post("/api/models", json={"activeProvider": "anthropic", "apiKey": "sk-unsaved"})
    assert r.status_code == 200
    assert r.json()["models"][0]["id"] == "claude-x"
    assert captured["api_key"] == "sk-unsaved"
    assert "apiKey" not in secretstore.load_store().get("connections", {}).get("claude", {})
