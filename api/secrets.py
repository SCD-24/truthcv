"""Fernet-encrypted provider secrets on the data volume.

Only this file is encrypted. A missing or invalid ENCRYPTION_KEY disables the
feature gracefully; provider credentials then come from environment variables.
Resolution order for any credential: secrets.enc (if the key is valid) -> env.
"""

from __future__ import annotations

import json
import os

from api.config import encryption_key, secrets_path

_FIELDS = ("activeProvider", "anthropicApiKey", "openaiApiKey", "ollamaHost", "model")


class SecretsUnavailable(RuntimeError):
    """Raised when a write is attempted without a valid ENCRYPTION_KEY."""


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
    except Exception:  # noqa: BLE001
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
