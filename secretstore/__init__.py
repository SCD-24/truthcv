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
    clean = {k: v for k, v in data.items() if v is not None}
    p = secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    token = f.encrypt(json.dumps(clean).encode("utf-8"))
    tmp = p.with_suffix(".enc.tmp")
    tmp.write_bytes(token)
    tmp.replace(p)


SCHEMA_VERSION = 2

_V1_KEY_MAP = (
    ("anthropicApiKey", "claude", "apiKey"),
    ("openaiApiKey", "codex", "apiKey"),
    ("ollamaHost", "ollama", "baseUrl"),
)


def migrate_v1(raw: dict) -> dict:
    """Lift a flat v1 secrets dict into the v2 connections shape. Pure."""
    if raw.get("version") == SCHEMA_VERSION:
        return raw
    connections: dict = {}
    for v1_key, card, field in _V1_KEY_MAP:
        if raw.get(v1_key):
            connections.setdefault(card, {})[field] = raw[v1_key]
    for card in ("claude", "codex"):
        if card in connections:
            connections[card]["authMode"] = "apikey"
    return {
        "version": SCHEMA_VERSION,
        "connections": connections,
        "legacyDefault": {
            "provider": raw.get("activeProvider", ""),
            "model": raw.get("model", ""),
        },
    }


def load_store() -> dict:
    """Return the v2 store, migrating a v1 file in place (with a .bak) once."""
    raw = read_secrets()
    if raw.get("version") == SCHEMA_VERSION:
        return raw
    store = migrate_v1(raw)
    if raw and encryption_available():
        p = secrets_path()
        if p.exists():
            bak = p.with_name("secrets.enc.v1.bak")
            if not bak.exists():
                bak.write_bytes(p.read_bytes())
        write_secrets(store)
    return store


def save_store(store: dict) -> None:
    write_secrets(store)


_ENV_KEY_FALLBACK = {"claude": "ANTHROPIC_API_KEY", "codex": "OPENAI_API_KEY"}
_V1_PROVIDER_TO_CARD = {"anthropic": "claude", "openai": "codex", "ollama": "ollama"}


def get_connection(card: str) -> dict:
    """Stored connection for a card, with env vars filling absent fields."""
    conn = dict(load_store().get("connections", {}).get(card, {}))
    env_var = _ENV_KEY_FALLBACK.get(card)
    if env_var and not conn.get("apiKey"):
        v = os.environ.get(env_var, "").strip()
        if v:
            conn["apiKey"] = v
    if card == "ollama" and not conn.get("baseUrl"):
        v = os.environ.get("OLLAMA_HOST", "").strip()
        conn["baseUrl"] = v if v else "http://localhost:11434"
    return conn


def set_connection(card: str, updates: dict) -> None:
    """Merge updates into a card's stored connection. None deletes a field."""
    store = load_store()
    conn = store.setdefault("connections", {}).setdefault(card, {})
    for k, v in updates.items():
        if v is None:
            conn.pop(k, None)
        else:
            conn[k] = v
    save_store(store)


def clear_mode(card: str, mode: str) -> None:
    if mode == "subscription":
        set_connection(card, {"oauth": None})
    else:
        set_connection(card, {"apiKey": None, "baseUrl": None, "bearer": None, "authMode": None})


def legacy_default() -> tuple[str | None, str]:
    """(card, model) equivalent of the v1 activeProvider/model behavior."""
    leg = load_store().get("legacyDefault", {})
    provider = (leg.get("provider") or os.environ.get("LLM_PROVIDER", "anthropic")).strip().lower()
    model = (leg.get("model") or os.environ.get("LLM_MODEL", "")).strip()
    return _V1_PROVIDER_TO_CARD.get(provider), model
