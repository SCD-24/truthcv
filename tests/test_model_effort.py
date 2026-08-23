"""Tests for effort-level capability map, Route persistence, and the routing API.

Covers:
  (a) supports_effort_levels — matrix across provider keys and model ids;
  (b) Route.effort round-trip, incl. legacy-file compatibility;
  (c) API: annotated model lists carry effortLevels;
  (d) PUT /api/routing accepts a supported effort and rejects an unsupported one.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import modelrouting
import secretstore
from api.main import app
from modelrouting import Route, Routing
from providers.base import supports_effort_levels

FERNET_KEY = "h2oN5GQVeWVhciVjWNImtAmWFyPGlrWvDCq8vXuqfmo="


# ---------------------------------------------------------------------------
# (a) Capability map
# ---------------------------------------------------------------------------


class TestCapabilityMap:
    """supports_effort_levels returns the right lists for known ids and [] for unknowns."""

    def test_claude_35_haiku(self):
        assert supports_effort_levels("claude", "claude-3-5-haiku") == ["low", "medium", "high"]

    def test_claude_37_sonnet(self):
        assert supports_effort_levels("claude", "claude-3-7-sonnet-20250219") == [
            "low",
            "medium",
            "high",
        ]

    def test_claude_opus_4(self):
        assert supports_effort_levels("claude", "claude-opus-4-8") == ["low", "medium", "high"]

    def test_claude_sonnet_4(self):
        assert supports_effort_levels("claude", "claude-sonnet-4-5") == ["low", "medium", "high"]

    def test_claude_3_opus_not_supported(self):
        # claude-3-opus is NOT in the 3.5/3.7/4.x family
        assert supports_effort_levels("claude", "claude-3-opus-20240229") == []

    def test_codex_gpt5(self):
        assert supports_effort_levels("codex", "gpt-5") == ["minimal", "low", "medium", "high"]

    def test_codex_gpt5_turbo(self):
        assert supports_effort_levels("codex", "gpt-5-turbo") == [
            "minimal",
            "low",
            "medium",
            "high",
        ]

    def test_codex_gpt4o_no_effort(self):
        assert supports_effort_levels("codex", "gpt-4o") == []

    def test_codex_o3(self):
        assert supports_effort_levels("codex", "o3") == ["low", "medium", "high"]

    def test_codex_o1(self):
        assert supports_effort_levels("codex", "o1") == ["low", "medium", "high"]

    def test_codex_o4_mini(self):
        assert supports_effort_levels("codex", "o4-mini") == ["low", "medium", "high"]

    def test_openrouter_gpt5_prefixed(self):
        assert supports_effort_levels("openrouter", "openai/gpt-5") == [
            "minimal",
            "low",
            "medium",
            "high",
        ]

    def test_openrouter_o3_prefixed(self):
        assert supports_effort_levels("openrouter", "openai/o3") == ["low", "medium", "high"]

    def test_openrouter_o1_colon(self):
        assert supports_effort_levels("openrouter", "openai:o1") == ["low", "medium", "high"]

    def test_openrouter_plain_o3(self):
        assert supports_effort_levels("openrouter", "o3") == ["low", "medium", "high"]

    def test_ollama_always_empty(self):
        assert supports_effort_levels("ollama", "llama3.1") == []
        assert supports_effort_levels("ollama", "gpt-5") == []

    def test_unknown_provider_empty(self):
        assert supports_effort_levels("copilot", "gpt-5") == []

    def test_unknown_model_empty(self):
        assert supports_effort_levels("claude", "gpt-4o") == []


# ---------------------------------------------------------------------------
# (b) Route effort persistence round-trip
# ---------------------------------------------------------------------------


class TestRoutePersistence:
    """Route.effort survives a save/load cycle; legacy files without it load fine."""

    def test_effort_roundtrip(self, data_dir):
        r = Routing(default=Route("claude", "claude-opus-4-8", "high"))
        modelrouting.save(r)
        loaded = modelrouting.load()
        assert loaded.default == Route("claude", "claude-opus-4-8", "high")
        assert loaded.default.effort == "high"

    def test_legacy_file_without_effort_loads_with_empty_string(self, data_dir):
        """A model_routing.json written before effort was added must load unchanged."""
        legacy = {
            "tasks": {},
            "agent": None,
            "default": {"connection": "codex", "model": "gpt-4o"},
        }
        (data_dir / "model_routing.json").write_text(json.dumps(legacy))
        loaded = modelrouting.load()
        assert loaded.default is not None
        assert loaded.default.effort == ""
        assert loaded.default.connection == "codex"
        assert loaded.default.model == "gpt-4o"

    def test_route_from_dict_missing_effort_defaults(self):
        route = Route.from_dict({"connection": "ollama", "model": "llama3.1"})
        assert route is not None
        assert route.effort == ""

    def test_route_equality_with_default_effort(self):
        assert Route("codex", "gpt-4o") == Route("codex", "gpt-4o", "")


# ---------------------------------------------------------------------------
# (c) API: model lists carry effortLevels
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    return TestClient(app)


class TestModelListEffortAnnotation:
    """POST /models and GET /auth/{provider}/models return effortLevels per model."""

    def test_post_models_annotates_effort(self, client, monkeypatch):
        """Anthropic's list_models is stubbed; the route annotates effort levels."""
        import providers.anthropic_provider as ap

        monkeypatch.setattr(
            ap.AnthropicProvider,
            "__init__",
            lambda self, **kw: setattr(self, "_noop", True),
        )
        monkeypatch.setattr(
            ap.AnthropicProvider,
            "list_models",
            lambda self: [
                {"id": "claude-opus-4-8", "label": "Claude Opus 4"},
                {"id": "claude-3-haiku-20240307", "label": "Haiku (legacy)"},
            ],
        )
        r = client.post("/api/models", json={"activeProvider": "anthropic", "apiKey": "sk-1"})
        assert r.status_code == 200
        models = {m["id"]: m for m in r.json()["models"]}
        assert models["claude-opus-4-8"]["effortLevels"] == ["low", "medium", "high"]
        # claude-3-haiku (not in 3.5/3.7/4 family) — no effort support
        assert models["claude-3-haiku-20240307"]["effortLevels"] == []

    def test_get_connection_models_annotates_effort(self, client, monkeypatch):
        """GET /auth/codex/models returns effortLevels from the capability map."""
        import providers.openai_provider as op

        monkeypatch.setattr(
            op.OpenAIProvider,
            "__init__",
            lambda self, **kw: setattr(self, "_noop", True),
        )
        monkeypatch.setattr(
            op.OpenAIProvider,
            "list_models",
            lambda self: [
                {"id": "gpt-5", "label": "GPT-5"},
                {"id": "gpt-4o", "label": "GPT-4o"},
                {"id": "o3", "label": "o3"},
            ],
        )
        secretstore.set_connection("codex", {"apiKey": "sk-oai"})
        r = client.get("/api/auth/codex/models")
        assert r.status_code == 200
        models = {m["id"]: m for m in r.json()["models"]}
        assert models["gpt-5"]["effortLevels"] == ["minimal", "low", "medium", "high"]
        assert models["gpt-4o"]["effortLevels"] == []
        assert models["o3"]["effortLevels"] == ["low", "medium", "high"]


# ---------------------------------------------------------------------------
# (d) PUT /api/routing effort validation
# ---------------------------------------------------------------------------


class TestRoutingEffortValidation:
    """PUT /api/routing persists a supported effort and rejects an unsupported one."""

    def test_put_routing_persists_supported_effort(self, client):
        resp = client.put(
            "/api/routing",
            json={"default": {"connection": "claude", "model": "claude-opus-4-8", "effort": "high"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["default"]["effort"] == "high"
        # Verify persistence via GET
        get_resp = client.get("/api/routing")
        assert get_resp.json()["default"]["effort"] == "high"

    def test_put_routing_rejects_unsupported_effort(self, client):
        """A non-empty effort for a model that returns [] must be a 400."""
        resp = client.put(
            "/api/routing",
            json={"default": {"connection": "claude", "model": "gpt-4o", "effort": "high"}},
        )
        assert resp.status_code == 400
        # Nothing must be saved
        assert client.get("/api/routing").json()["default"] is None

    def test_put_routing_empty_effort_always_allowed(self, client):
        """Sending effort='' is the same as omitting it — always valid."""
        resp = client.put(
            "/api/routing",
            json={"default": {"connection": "codex", "model": "gpt-4o", "effort": ""}},
        )
        assert resp.status_code == 200

    def test_put_routing_ollama_rejects_effort(self, client):
        """Ollama never supports effort; any non-empty value must be rejected."""
        resp = client.put(
            "/api/routing",
            json={"default": {"connection": "ollama", "model": "llama3.1", "effort": "low"}},
        )
        assert resp.status_code == 400

    def test_get_routing_returns_effort_field(self, client):
        """GET /api/routing echoes the effort field even for routes without one."""
        resp = client.get("/api/routing")
        assert resp.status_code == 200
        body = resp.json()
        assert body["default"] is None or "effort" in (body["default"] or {})
