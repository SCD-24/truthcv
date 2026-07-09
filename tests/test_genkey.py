"""api.genkey produces a valid Fernet key."""

from __future__ import annotations


def test_generate_makes_valid_fernet_key():
    from cryptography.fernet import Fernet

    from api.genkey import generate

    key = generate()
    Fernet(key.encode("utf-8"))  # raises if invalid
    assert len(key) >= 40
