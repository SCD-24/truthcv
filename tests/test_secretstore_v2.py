import json

import pytest

import secretstore
from cryptography.fernet import Fernet


@pytest.fixture()
def enc(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    return data_dir


def _write_v1(payload: dict):
    secretstore.write_secrets(payload)


def test_migrate_v1_maps_fields():
    out = secretstore.migrate_v1(
        {
            "activeProvider": "anthropic",
            "anthropicApiKey": "sk-ant-1",
            "openaiApiKey": "sk-oai-1",
            "ollamaHost": "http://box:11434",
            "model": "claude-opus-4-8",
        }
    )
    assert out["version"] == 2
    assert out["connections"]["claude"] == {"apiKey": "sk-ant-1", "authMode": "apikey"}
    assert out["connections"]["codex"] == {"apiKey": "sk-oai-1", "authMode": "apikey"}
    assert out["connections"]["ollama"] == {"baseUrl": "http://box:11434"}
    assert out["legacyDefault"] == {"provider": "anthropic", "model": "claude-opus-4-8"}


def test_migrate_v2_passthrough():
    v2 = {"version": 2, "connections": {"claude": {"apiKey": "x"}}}
    assert secretstore.migrate_v1(v2) is v2


def test_load_store_migrates_persists_and_writes_bak(enc):
    _write_v1({"activeProvider": "openai", "openaiApiKey": "sk-oai-2", "model": "gpt-4o"})
    store = secretstore.load_store()
    assert store["connections"]["codex"]["apiKey"] == "sk-oai-2"
    assert (enc / "secrets.enc.v1.bak").exists()
    # persisted as v2: reading again does not re-migrate (idempotent)
    again = secretstore.load_store()
    assert again["version"] == 2
    assert secretstore.read_secrets()["version"] == 2


def test_load_store_env_only_returns_v2_without_writing(data_dir, monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    store = secretstore.load_store()
    assert store["version"] == 2
    assert not (data_dir / "secrets.enc").exists()


def test_write_secrets_no_longer_drops_unknown_keys(enc):
    secretstore.write_secrets({"version": 2, "connections": {"claude": {"oauth": {"accessToken": "t"}}}})
    assert secretstore.read_secrets()["connections"]["claude"]["oauth"]["accessToken"] == "t"
