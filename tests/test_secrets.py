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
    """Same behavior the old resolve_credentials() covered, via the v2
    accessors it was replaced by: get_connection merges stored-over-env."""
    from secretstore import get_connection

    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    sec.write_secrets({"activeProvider": "anthropic", "anthropicApiKey": "enc-key"})
    assert get_connection("claude")["apiKey"] == "enc-key"  # secrets wins over env
    assert get_connection("codex").get("apiKey", "") == ""  # absent everywhere


def test_invalid_key_disables(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "not-a-valid-fernet-key")
    assert sec.encryption_available() is False
    assert sec.read_secrets() == {}


def test_wrong_key_after_rotation_refuses_overwrite(data_dir, monkeypatch):
    """A rotated/wrong ENCRYPTION_KEY must refuse to overwrite secrets.enc and
    instead back it up, so still-encrypted credentials are never destroyed."""
    import secretstore
    from cryptography.fernet import Fernet

    from api.config import secrets_path

    # A different, valid Fernet key to simulate rotation.
    fernet_key_b = Fernet.generate_key().decode("utf-8")
    assert fernet_key_b != FERNET_KEY

    # Write secrets.enc with key A.
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    secretstore.save_store(
        {"version": 2, "connections": {"claude": {"apiKey": "old-secret"}}}
    )
    p = secrets_path()
    original = p.read_bytes()

    # Rotate to a different valid key B — decryption of the old blob will fail.
    monkeypatch.setenv("ENCRYPTION_KEY", fernet_key_b)

    with pytest.raises(secretstore.SecretsDecryptError):
        secretstore.load_store()

    # The original file was NOT overwritten.
    assert p.read_bytes() == original

    # A backup of the raw bytes now exists.
    backups = list(p.parent.glob("secrets.enc.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original

    # The shim re-exports the exception too.
    assert sec.SecretsDecryptError is secretstore.SecretsDecryptError
