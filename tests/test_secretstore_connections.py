import pytest

import secretstore
from cryptography.fernet import Fernet


@pytest.fixture()
def enc(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    return data_dir


def test_set_and_get_connection(enc):
    secretstore.set_connection("claude", {"apiKey": "sk-ant-9", "authMode": "apikey"})
    assert secretstore.get_connection("claude")["apiKey"] == "sk-ant-9"


def test_env_fallback_fills_missing_key(enc, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    assert secretstore.get_connection("claude")["apiKey"] == "sk-env"
    secretstore.set_connection("claude", {"apiKey": "sk-stored"})
    assert secretstore.get_connection("claude")["apiKey"] == "sk-stored"  # stored wins


def test_ollama_baseurl_default(enc):
    assert secretstore.get_connection("ollama")["baseUrl"] == "http://localhost:11434"


def test_clear_mode(enc):
    secretstore.set_connection("claude", {"oauth": {"accessToken": "t"}, "apiKey": "k"})
    secretstore.clear_mode("claude", "subscription")
    conn = secretstore.load_store()["connections"]["claude"]
    assert "oauth" not in conn and conn["apiKey"] == "k"


def test_legacy_default_from_migration(enc):
    secretstore.write_secrets({"activeProvider": "openai", "model": "gpt-4o"})
    assert secretstore.legacy_default() == ("codex", "gpt-4o")


def test_legacy_default_from_env(enc, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "llama3.1")
    assert secretstore.legacy_default() == ("ollama", "llama3.1")
