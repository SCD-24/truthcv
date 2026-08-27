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
import time
from pathlib import Path


class SecretsUnavailable(RuntimeError):
    """Raised when a write is attempted without a valid ENCRYPTION_KEY."""


class SecretsDecryptError(RuntimeError):
    """Raised when secrets.enc exists but cannot be decrypted with the current ENCRYPTION_KEY."""


def encryption_key() -> str:
    """Fernet master key from the environment (empty if unset)."""
    return os.environ.get("ENCRYPTION_KEY", "").strip()


def secrets_path() -> Path:
    """Location of the encrypted secrets blob on the data volume."""
    from storage import data_dir

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
    """Decrypt and return stored secrets.

    Returns {} when secrets are genuinely unavailable: no valid ENCRYPTION_KEY
    (``f is None``) or no file on disk. But when the file EXISTS yet cannot be
    decrypted/parsed with the current key (rotated/wrong key, corrupt blob),
    raise SecretsDecryptError rather than masquerading as absent — silently
    returning {} there would let a later write overwrite and destroy the blob.
    """
    f = _fernet()
    p = secrets_path()
    if f is None or not p.exists():
        return {}
    try:
        return json.loads(f.decrypt(p.read_bytes()).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — file present but undecryptable/unparseable
        raise SecretsDecryptError(
            "secrets.enc exists but could not be decrypted with the current ENCRYPTION_KEY."
        ) from exc


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
    """Return the v2 store, migrating a v1 file in place (with a .bak) once.

    If secrets.enc exists but cannot be decrypted (wrong/rotated key), back up
    the raw bytes and re-raise so no subsequent write can overwrite and destroy
    the still-encrypted credentials.
    """
    try:
        raw = read_secrets()
    except SecretsDecryptError:
        p = secrets_path()
        if p.exists():
            bak = p.with_name(f"secrets.enc.corrupt-{int(time.time())}.bak")
            if not bak.exists():
                bak.write_bytes(p.read_bytes())
        raise
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


def _load_store_for_read() -> dict:
    """Like load_store(), but for read paths that must keep degrading to env
    vars (per the documented secrets.enc -> env resolution order) rather than
    raising when secrets.enc is present but undecryptable. Write paths
    (set_connection/save_store) go through load_store() directly so they
    still refuse to overwrite an undecryptable store."""
    try:
        return load_store()
    except SecretsDecryptError:
        return {}


def get_connection(card: str) -> dict:
    """Stored connection for a card, with env vars filling absent fields."""
    conn = dict(_load_store_for_read().get("connections", {}).get(card, {}))
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
    leg = _load_store_for_read().get("legacyDefault", {})
    provider = (leg.get("provider") or os.environ.get("LLM_PROVIDER", "anthropic")).strip().lower()
    model = (leg.get("model") or os.environ.get("LLM_MODEL", "")).strip()
    return _V1_PROVIDER_TO_CARD.get(provider), model
