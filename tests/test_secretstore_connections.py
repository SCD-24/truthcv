import stat
import sys
import threading

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


def test_ollama_baseurl_empty_env_uses_default(enc, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "")
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


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX file mode only")
def test_secrets_file_mode_is_0600(enc):
    secretstore.set_connection("claude", {"apiKey": "sk-ant-9"})
    mode = stat.S_IMODE(secretstore.secrets_path().stat().st_mode)
    assert mode == 0o600


def test_read_paths_work_when_lock_sidecar_cannot_be_created(enc, monkeypatch):
    def boom(*a, **k):
        raise OSError("read-only filesystem")

    monkeypatch.setattr("storage.atomic.locked", boom)

    # No secrets.enc yet: pure reads must not touch the lock at all.
    assert secretstore.get_connection("claude") == {}
    assert secretstore.load_store()["connections"] == {}


def test_concurrent_set_connection_for_different_cards(enc):
    errors = []

    def worker(card, key):
        try:
            for _ in range(20):
                secretstore.set_connection(card, {"apiKey": key})
        except Exception as exc:  # noqa: BLE001 — surface any thread failure
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("claude", "sk-ant-x")),
        threading.Thread(target=worker, args=("codex", "sk-oai-y")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    store = secretstore.load_store()
    assert store["connections"]["claude"]["apiKey"] == "sk-ant-x"
    assert store["connections"]["codex"]["apiKey"] == "sk-oai-y"
    assert not secretstore.secrets_path().with_suffix(".enc.tmp").exists()
