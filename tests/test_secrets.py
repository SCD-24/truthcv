"""Fernet secrets store: encryption, graceful disable, credential resolution."""

from __future__ import annotations

import pytest

from api import secrets as sec

FERNET_KEY = "h2oN5GQVeWVhciVjWNImtAmWFyPGlrWvDCq8vXuqfmo="  # valid Fernet key


def test_no_encryption_key_disables(data_dir, monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    assert sec.encryption_available() is False
    assert sec.read_secrets() == {}
    with pytest.raises(sec.SecretsUnavailable):
        sec.write_secrets({"activeProvider": "anthropic"})


def test_round_trip_encrypted(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    sec.write_secrets({"activeProvider": "openai", "openaiApiKey": "sk-x"})
    assert sec.encryption_available() is True
    got = sec.read_secrets()
    assert got["openaiApiKey"] == "sk-x"
    # file on disk is NOT plaintext
    from api.config import secrets_path

    raw = secrets_path().read_bytes()
    assert b"sk-x" not in raw


def test_resolve_prefers_secrets_then_env(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    sec.write_secrets({"activeProvider": "anthropic", "anthropicApiKey": "enc-key"})
    creds = sec.resolve_credentials()
    assert creds["anthropicApiKey"] == "enc-key"  # secrets wins
    assert creds["openaiApiKey"] == ""  # absent everywhere


def test_invalid_key_disables(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "not-a-valid-fernet-key")
    assert sec.encryption_available() is False
    assert sec.read_secrets() == {}
