"""Neutral credential + secrets layer, depended on downward by both api and providers.

Why this package exists: the provider layer needs resolved credentials, but it must
not import the api layer to get them — that made providers depend *up* on api and
formed the project's only import cycle. Housing credential resolution here (a leaf
that imports only truth.store for the data path) lets both api and providers depend
on it downward, breaking the cycle.

Resolution order for any credential: secrets.enc (if ENCRYPTION_KEY is valid) -> env.
Only secrets.enc is encrypted; a missing/invalid key disables encryption gracefully
and credentials then come from environment variables.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_FIELDS = ("activeProvider", "anthropicApiKey", "openaiApiKey", "ollamaHost", "model")


class SecretsUnavailable(RuntimeError):
    """Raised when a write is attempted without a valid ENCRYPTION_KEY."""


def encryption_key() -> str:
    """Fernet master key from the environment (empty if unset)."""
    return os.environ.get("ENCRYPTION_KEY", "").strip()


def secrets_path() -> Path:
    """Location of the encrypted secrets blob on the data volume."""
    from truth.store import data_dir

    return data_dir() / "secrets.enc"


def _fernet():
    key = encryption_key()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(key.encode("utf-8"))
    except Exception:  # noqa: BLE001 — any invalid key disables the feature
        return None


def encryption_available() -> bool:
    return _fernet() is not None


def read_secrets() -> dict:
    """Decrypt and return stored secrets, or {} if unavailable/absent/corrupt."""
    f = _fernet()
    p = secrets_path()
    if f is None or not p.exists():
        return {}
    try:
        return json.loads(f.decrypt(p.read_bytes()).decode("utf-8"))
    except Exception:  # noqa: BLE001 — corrupt/foreign blob behaves as absent
        return {}


def write_secrets(data: dict) -> None:
    """Encrypt and atomically persist the given secrets."""
    f = _fernet()
    if f is None:
        raise SecretsUnavailable("ENCRYPTION_KEY is missing or invalid.")
    clean = {k: v for k, v in data.items() if k in _FIELDS and v is not None}
    p = secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    token = f.encrypt(json.dumps(clean).encode("utf-8"))
    tmp = p.with_suffix(".enc.tmp")
    tmp.write_bytes(token)
    tmp.replace(p)


def resolve_credentials() -> dict:
    """Merge stored secrets over environment defaults.

    Returns every field in _FIELDS; secrets.enc values win where present,
    otherwise the environment variable, otherwise a sensible default.
    """
    s = read_secrets()
    out = {
        "activeProvider": os.environ.get("LLM_PROVIDER", "anthropic"),
        "anthropicApiKey": os.environ.get("ANTHROPIC_API_KEY", ""),
        "openaiApiKey": os.environ.get("OPENAI_API_KEY", ""),
        "ollamaHost": os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        "model": os.environ.get("LLM_MODEL", ""),
    }
    for k in _FIELDS:
        v = s.get(k)
        if v:
            out[k] = v
    return out
