"""services.settings: error branches and key return shapes.

The data volume is isolated per test by conftest; providers are fakes.
"""

from __future__ import annotations

import pytest

import modelrouting
import secretstore
from providers import ProviderError
from services import settings
from services.errors import BadGateway, BadRequest

FERNET_KEY = "h2oN5GQVeWVhciVjWNImtAmWFyPGlrWvDCq8vXuqfmo="


@pytest.fixture()
def encrypted(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)


@pytest.fixture()
def resets(monkeypatch):
    calls = []
    monkeypatch.setattr("providers.reset_provider", lambda: calls.append(1))
    return calls


def test_update_jev_without_encryption_is_bad_request(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    with pytest.raises(BadRequest, match=r"^Set ENCRYPTION_KEY in \.env first\.$"):
        settings.update_jev(None, True, None)


def test_update_jev_saves_and_returns_status(encrypted):
    status = settings.update_jev(" k ", True, None)
    assert status == {
        "key_set": True,
        "use_for_screening": True,
        "use_for_email_tracking": False,
        "encryption_available": True,
    }
    assert secretstore.get_connection("jev")["apiKey"] == "k"


def test_save_v1_settings_without_encryption(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    with pytest.raises(BadRequest, match=r"^Set ENCRYPTION_KEY in \.env first\.$"):
        settings.save_v1_settings("anthropic", "k", None, None)


def test_save_v1_settings_unknown_provider(encrypted):
    with pytest.raises(BadRequest, match=r"^Unknown provider 'nope'\.$"):
        settings.save_v1_settings("nope", "k", None, None)


def test_save_v1_settings_writes_default_and_resets(encrypted, resets):
    status = settings.save_v1_settings("anthropic", "sk", None, "m1")
    assert status["active_provider"] == "anthropic"
    assert status["model"] == "m1"
    assert status["anthropic_key_set"] is True
    assert modelrouting.load().default == modelrouting.Route("claude", "m1")
    assert resets == [1]


def test_test_v1_settings_reports_service_error(encrypted):
    ok, detail = settings.test_v1_settings("nope", None, None, None, provider_factory=None)
    assert (ok, detail) == (False, "Unknown provider 'nope'.")


def test_test_v1_settings_reports_provider_failure(encrypted, resets):
    class Boom:
        def complete(self, *_a):
            raise RuntimeError("down")

    ok, detail = settings.test_v1_settings("anthropic", "k", None, None, lambda: Boom())
    assert (ok, detail) == (False, "RuntimeError: down")


def test_test_v1_settings_success(encrypted, resets):
    class Ok:
        def complete(self, *_a):
            return "pong"

    assert settings.test_v1_settings("anthropic", "k", None, None, lambda: Ok()) == (
        True,
        "Connection succeeded.",
    )


def _classes(monkeypatch, list_models):
    """Patch each provider class on its own module, where list_v1_models looks it up."""
    import providers.anthropic_provider as anthropic_mod
    import providers.ollama_provider as ollama_mod
    import providers.openai_provider as openai_mod

    class Fake:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def list_models(self):
            return list_models()

    monkeypatch.setattr(anthropic_mod, "AnthropicProvider", Fake)
    monkeypatch.setattr(openai_mod, "OpenAIProvider", Fake)
    monkeypatch.setattr(ollama_mod, "OllamaProvider", Fake)


def test_list_v1_models_unknown_provider(monkeypatch):
    _classes(monkeypatch, list)
    with pytest.raises(BadRequest, match=r"^Unknown provider 'nope'\.$"):
        settings.list_v1_models(" NOPE ", None, None)


def test_list_v1_models_provider_error_is_bad_request(monkeypatch):
    def fail():
        raise ProviderError("no key")

    _classes(monkeypatch, fail)

    with pytest.raises(BadRequest, match=r"^no key$"):
        settings.list_v1_models("anthropic", None, None)


def test_list_v1_models_other_error_is_bad_gateway(monkeypatch):
    def fail():
        raise ValueError("bad json")

    _classes(monkeypatch, fail)

    with pytest.raises(BadGateway, match=r"^ValueError: bad json$"):
        settings.list_v1_models("openai", None, None)


def test_list_v1_models_returns_models_and_card(monkeypatch):
    models = [{"id": "llama3"}]
    _classes(monkeypatch, lambda: models)
    assert settings.list_v1_models("ollama", None, "http://h") == (
        models,
        "ollama",
    )


def test_update_routing_unknown_connection():
    with pytest.raises(BadRequest, match=r"^unknown connection: nope$"):
        settings.update_routing({"default": {"connection": "nope", "model": "m"}})


def test_update_routing_unsupported_effort():
    with pytest.raises(BadRequest, match=r"^effort 'high' is not supported for ollama/llama3$"):
        settings.update_routing(
            {"tasks": {"t": {"connection": "ollama", "model": "llama3", "effort": "high"}}}
        )


def test_update_routing_null_clears_and_resets(resets):
    settings.update_routing({"tasks": {"t": {"connection": "claude", "model": "m"}}})
    routing = settings.update_routing({"tasks": {"t": None}, "default": None})
    assert routing.tasks == {} and routing.default is None
    assert modelrouting.load().tasks == {}
    assert resets == [1, 1]
