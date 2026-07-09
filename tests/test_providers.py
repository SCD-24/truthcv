"""Provider-layer selection and FakeProvider behavior (no network)."""

from __future__ import annotations

import pytest

from providers import ProviderError, get_provider
from providers.fake import FakeProvider


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    from providers import reset_provider

    reset_provider()
    yield
    reset_provider()


def test_get_provider_defaults_and_selects(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    from providers import reset_provider

    reset_provider()
    assert isinstance(get_provider(), FakeProvider)


def test_get_provider_unknown_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    from providers import reset_provider

    reset_provider()
    with pytest.raises(ProviderError):
        get_provider(refresh=True)


def test_get_provider_uses_secrets_credentials(data_dir, monkeypatch):
    from providers import get_provider, reset_provider

    monkeypatch.setenv("ENCRYPTION_KEY", "h2oN5GQVeWVhciVjWNImtAmWFyPGlrWvDCq8vXuqfmo=")
    from api import secrets as sec

    sec.write_secrets({"activeProvider": "fake"})  # active provider from secrets
    reset_provider()
    from providers.fake import FakeProvider

    assert isinstance(get_provider(refresh=True), FakeProvider)


def test_env_model_treats_empty_as_default(monkeypatch):
    from providers.base import env_model

    monkeypatch.setenv("LLM_MODEL", "")
    assert env_model("default-model") == "default-model"
    monkeypatch.setenv("LLM_MODEL", "   ")
    assert env_model("default-model") == "default-model"
    monkeypatch.setenv("LLM_MODEL", "custom")
    assert env_model("default-model") == "custom"
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert env_model("default-model") == "default-model"
    assert env_model("default-model", "override") == "override"


def test_fake_completions_consumed_in_order():
    p = FakeProvider(completions=["a", "b"])
    assert p.complete("s", [{"role": "user", "content": "x"}]) == "a"
    assert p.complete("s", []) == "b"
    assert p.complete("s", []) == ""  # exhausted -> empty


def test_fake_json_queue_and_schema_default():
    p = FakeProvider(json_responses=[{"entries": [{"id": "1"}]}])
    schema = {"type": "object", "properties": {"entries": {"type": "array"}}}
    assert p.extract_json("s", [], schema) == {"entries": [{"id": "1"}]}
    # exhausted -> schema-shaped empty
    assert p.extract_json("s", [], schema) == {"entries": []}


def test_fake_router_overrides_queue():
    def router(system, messages, schema):
        return {"entries": ["routed"]} if schema else "routed-text"

    p = FakeProvider(router=router)
    assert p.complete("s", []) == "routed-text"
    assert p.extract_json("s", [], {"type": "object"}) == {"entries": ["routed"]}


def test_fake_records_calls():
    p = FakeProvider(completions=["a"])
    p.complete("sys", [{"role": "user", "content": "hi"}])
    assert p.calls[0]["kind"] == "complete"
    assert p.calls[0]["system"] == "sys"
