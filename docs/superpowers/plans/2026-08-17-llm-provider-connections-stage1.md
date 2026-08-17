# LLM Provider Connections — Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-connection provider accounts (Claude subscription OAuth + API-key providers), encrypted v2 secret store with lossless v1 migration, a routing store with default-only resolution, and the Accounts UI in Settings.

**Architecture:** A new leaf package `connections/` (catalog + vendor auth flows) and `modelrouting/` (non-secret routing store) sit beside the reworked `secretstore` (v2 versioned schema, per-connection accessors, env fallback). `providers.get_provider(task)` resolves routing → connection → cached provider instance. FastAPI routes expose the aether-style `/api/auth/*` surface; the Settings modal replaces its single-provider panel with Accounts + Default model sections.

**Tech Stack:** Python 3.11, FastAPI, pydantic (`_Camel` wire models), httpx + respx (tests), cryptography/Fernet, anthropic + openai SDKs; React 18 + TS + MUI v9, vitest.

**Spec:** `docs/superpowers/specs/2026-08-17-llm-provider-connections-design.md`

**Reference implementation (read-only):** `/mnt/projects/code/aether` — port flows from `server/auth/claude.js`; do not copy code verbatim (Node → Python).

## Global Constraints

- Migration is lossless and idempotent: existing keys are NEVER re-entered; `secrets.enc.v1.bak` written before any v1 rewrite.
- Env fallback preserved exactly: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_HOST`, `LLM_PROVIDER`, `LLM_MODEL` keep working with no stored config.
- Secrets never reach the browser: status responses carry booleans/metadata only. Never log tokens or keys.
- Anthropic subscription calls: `Authorization: Bearer` (SDK `auth_token=`), header `anthropic-beta: oauth-2025-04-20`, and the literal first system block `"You are Claude Code, Anthropic's official CLI for Claude."`
- Empty/absent key on write keeps the stored key (existing convention).
- Stage 1 catalog cards: `claude`, `codex`, `openrouter`, `ollama`. Copilot/Antigravity arrive in Stage 3.
- Follow existing patterns: `_Camel` schemas, atomic tmp+rename writes, defensive `from_dict`, `data_dir()` paths, colocated vitest tests.
- Test commands: `python -m pytest tests/ -q` (backend, repo root), `npm test` in `web/` (frontend). Build check: `npm run build` in `web/`.
- Commit per task on the feature branch (`git checkout -b feat/provider-connections` before Task 1 if not on it). Never commit to a default branch.

---

### Task 1: Provider catalog

**Files:**
- Create: `connections/__init__.py` (empty docstring module)
- Create: `connections/catalog.py`
- Test: `tests/test_connections_catalog.py`

**Interfaces:**
- Produces: `connections.catalog.CARDS: dict[str, dict]`, `card_keys() -> tuple[str, ...]`, `card(key) -> dict` (raises `KeyError` on unknown).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_connections_catalog.py
from connections.catalog import CARDS, card, card_keys


def test_stage1_cards_present():
    assert card_keys() == ("claude", "codex", "openrouter", "ollama")


def test_card_shapes():
    assert card("claude")["modes"] == ("subscription", "apikey")
    assert card("codex")["modes"] == ("apikey",)
    assert card("openrouter")["modes"] == ("apikey",)
    assert card("ollama")["modes"] == ("url",)
    for c in CARDS.values():
        assert c["label"]


def test_unknown_card_raises():
    import pytest
    with pytest.raises(KeyError):
        card("copilot")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_connections_catalog.py -q`
Expected: FAIL — `ModuleNotFoundError: connections`

- [ ] **Step 3: Implement**

```python
# connections/__init__.py
"""Provider connection layer: catalog + per-vendor auth flows."""
```

```python
# connections/catalog.py
"""Static catalog of provider connection cards.

Stage 1 ships claude (subscription + apikey), codex (apikey only — its
subscription OAuth lands in stage 3), openrouter, ollama. Model lists are
never hardcoded; they are discovered live per connection.
"""

from __future__ import annotations

CARDS: dict[str, dict] = {
    "claude": {"label": "Claude (Anthropic)", "modes": ("subscription", "apikey")},
    "codex": {"label": "ChatGPT (OpenAI)", "modes": ("apikey",)},
    "openrouter": {"label": "OpenRouter", "modes": ("apikey",)},
    "ollama": {"label": "Ollama", "modes": ("url",)},
}


def card_keys() -> tuple[str, ...]:
    return tuple(CARDS.keys())


def card(key: str) -> dict:
    return CARDS[key]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_connections_catalog.py -q` — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add connections/ tests/test_connections_catalog.py
git commit -m "feat: provider connection catalog (stage 1 cards)"
```

---

### Task 2: secretstore v2 schema + lossless migration

**Files:**
- Modify: `secretstore/__init__.py` (remove `_FIELDS` filtering in `write_secrets`; add `migrate_v1`, `load_store`, `save_store`)
- Test: `tests/test_secretstore_v2.py`

**Interfaces:**
- Consumes: existing `read_secrets()`, `write_secrets()`, `encryption_available()`, `secrets_path()`.
- Produces: `migrate_v1(raw: dict) -> dict` (pure), `load_store() -> dict` (always returns a v2-shaped dict `{"version": 2, "connections": {...}, "legacyDefault": {...}}`; persists the migration and writes `secrets.enc.v1.bak` when encryption is available and a v1 file existed), `save_store(store: dict) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_secretstore_v2.py
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_secretstore_v2.py -q`
Expected: FAIL — `AttributeError: module 'secretstore' has no attribute 'migrate_v1'` (and the unknown-keys test fails against the `_FIELDS` filter)

- [ ] **Step 3: Implement**

In `secretstore/__init__.py`: delete the `_FIELDS` constant; in `write_secrets` replace the `clean = ...` line with `clean = {k: v for k, v in data.items() if v is not None}`; append:

```python
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
```

- [ ] **Step 4: Run the new tests AND the full suite** (the `_FIELDS` removal touches existing settings tests)

Run: `python -m pytest tests/ -q` — Expected: PASS (if `tests/test_settings_api.py` asserted whitelist-dropping, update those assertions to the new passthrough behavior and note it in the commit)

- [ ] **Step 5: Commit**

```bash
git add secretstore/__init__.py tests/
git commit -m "feat: secretstore v2 schema with lossless idempotent v1 migration"
```

---

### Task 3: Connection accessors + env fallback + legacy default

**Files:**
- Modify: `secretstore/__init__.py`
- Test: `tests/test_secretstore_connections.py`

**Interfaces:**
- Produces: `get_connection(card: str) -> dict` (stored connection merged with env fallback), `set_connection(card: str, updates: dict) -> None` (None value deletes a field; raises `SecretsUnavailable` without encryption), `clear_mode(card: str, mode: str) -> None` (`"subscription"` pops `oauth`; anything else pops `apiKey`/`baseUrl`/`bearer`/`authMode`), `legacy_default() -> tuple[str | None, str]` (card key or None, model).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_secretstore_connections.py
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_secretstore_connections.py -q` — Expected: FAIL (`AttributeError`)

- [ ] **Step 3: Implement** (append to `secretstore/__init__.py`)

```python
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
        conn["baseUrl"] = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
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
```

- [ ] **Step 4: Run** `python -m pytest tests/test_secretstore_connections.py tests/test_secretstore_v2.py -q` — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add secretstore/__init__.py tests/test_secretstore_connections.py
git commit -m "feat: per-connection secret accessors with env fallback"
```

---

### Task 4: modelrouting store

**Files:**
- Create: `modelrouting/__init__.py`, `modelrouting/store.py`
- Modify: `Dockerfile` (add `COPY modelrouting/ ./modelrouting/` and `COPY connections/ ./connections/` beside the existing package COPY lines, `Dockerfile:31-45`)
- Test: `tests/test_modelrouting.py`

**Interfaces:**
- Produces: `modelrouting.TASK_NAMES = ("truth_extract", "keywords", "tailor", "infer", "cover_letter")`; `Route(connection: str, model: str = "")`; `Routing(tasks: dict[str, Route], agent: Route | None, default: Route | None)` with `from_dict`/`to_dict`; `load() -> Routing`; `save(r: Routing) -> Routing`; `resolve(r: Routing, task: str | None) -> Route | None` (task entry → default → None).
- Storage: `data_dir()/model_routing.json`, atomic tmp+rename, defensive parse — mirror `agentconfig/store.py` exactly.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_modelrouting.py
import modelrouting
from modelrouting import Route, Routing


def test_roundtrip(data_dir):
    r = Routing(
        tasks={"cover_letter": Route("claude", "claude-opus-4-8")},
        agent=Route("claude", ""),
        default=Route("codex", "gpt-4o"),
    )
    modelrouting.save(r)
    loaded = modelrouting.load()
    assert loaded.default == Route("codex", "gpt-4o")
    assert loaded.tasks["cover_letter"].model == "claude-opus-4-8"


def test_load_missing_file_gives_empty(data_dir):
    r = modelrouting.load()
    assert r.tasks == {} and r.agent is None and r.default is None


def test_from_dict_ignores_garbage(data_dir):
    r = Routing.from_dict({"tasks": {"keywords": {"connection": 5}}, "default": "nope", "junk": 1})
    assert r.tasks == {} and r.default is None


def test_resolve_ladder():
    r = Routing(tasks={"keywords": Route("ollama", "llama3.1")}, agent=None, default=Route("claude"))
    assert modelrouting.resolve(r, "keywords").connection == "ollama"
    assert modelrouting.resolve(r, "tailor").connection == "claude"
    assert modelrouting.resolve(r, None).connection == "claude"
    assert modelrouting.resolve(Routing(), "keywords") is None
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_modelrouting.py -q` — FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement**

```python
# modelrouting/__init__.py
"""Non-secret model routing: which connection+model each task/agent uses."""

from .store import TASK_NAMES, Route, Routing, load, resolve, save

__all__ = ["TASK_NAMES", "Route", "Routing", "load", "resolve", "save"]
```

```python
# modelrouting/store.py
"""Routing store. Storage: data_dir()/model_routing.json (not secret)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from truth.store import data_dir

TASK_NAMES = ("truth_extract", "keywords", "tailor", "infer", "cover_letter")


def routing_path() -> Path:
    return data_dir() / "model_routing.json"


@dataclass(frozen=True)
class Route:
    connection: str
    model: str = ""

    @classmethod
    def from_dict(cls, raw: object) -> Route | None:
        if not isinstance(raw, dict) or not isinstance(raw.get("connection"), str):
            return None
        model = raw.get("model")
        return cls(raw["connection"], model if isinstance(model, str) else "")

    def to_dict(self) -> dict:
        return {"connection": self.connection, "model": self.model}


@dataclass
class Routing:
    tasks: dict[str, Route] = field(default_factory=dict)
    agent: Route | None = None
    default: Route | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> Routing:
        tasks: dict[str, Route] = {}
        raw_tasks = raw.get("tasks")
        if isinstance(raw_tasks, dict):
            for name in TASK_NAMES:
                route = Route.from_dict(raw_tasks.get(name))
                if route:
                    tasks[name] = route
        return cls(
            tasks=tasks,
            agent=Route.from_dict(raw.get("agent")),
            default=Route.from_dict(raw.get("default")),
        )

    def to_dict(self) -> dict:
        return {
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "agent": self.agent.to_dict() if self.agent else None,
            "default": self.default.to_dict() if self.default else None,
        }


def load() -> Routing:
    p = routing_path()
    if not p.exists():
        return Routing()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return Routing()
    return Routing.from_dict(raw) if isinstance(raw, dict) else Routing()


def save(r: Routing) -> Routing:
    p = routing_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(r.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(p)
    return r


def resolve(r: Routing, task: str | None) -> Route | None:
    if task and task in r.tasks:
        return r.tasks[task]
    return r.default
```

In `Dockerfile`, next to the existing package COPY lines, add:

```dockerfile
COPY connections/ ./connections/
COPY modelrouting/ ./modelrouting/
```

- [ ] **Step 4: Run** `python -m pytest tests/test_modelrouting.py -q` — PASS

- [ ] **Step 5: Commit**

```bash
git add modelrouting/ Dockerfile tests/test_modelrouting.py
git commit -m "feat: model routing store (tasks/agent/default)"
```

---

### Task 5: Claude subscription OAuth module

**Files:**
- Create: `connections/auth/__init__.py` (empty docstring), `connections/auth/claude.py`
- Test: `tests/test_auth_claude.py`
- Reference: port constants and flow exactly from `/mnt/projects/code/aether/server/auth/claude.js` (client id, URLs, scopes, paste-code `code#state` format, refresh-preserves-old-refresh-token). Verify each constant against that file; do not invent values.

**Interfaces:**
- Consumes: `secretstore.get_connection` / `set_connection`.
- Produces: `CLAUDE_CODE_PREAMBLE: str`; `start_login() -> dict` (`{"flow": "paste-code", "authUrl": ...}`; keeps PKCE verifier + state in module memory only); `complete_login(code_state: str) -> dict` (exchanges, persists oauth record, returns non-secret metadata `{"connectedAt", "expiresAt", "scope"}`); `get_valid_access_token() -> str` (refresh under `threading.Lock` when < 300 s to expiry; raises `AuthError` when disconnected or refresh fails); `AuthError(RuntimeError)`.
- OAuth record shape (stored under `connections.claude.oauth`): `{"accessToken", "refreshToken", "expiresAt" (epoch seconds), "scope", "connectedAt"}`.

- [ ] **Step 1: Write the failing tests** (respx is the mock layer; add `respx` to a dev requirements file if the repo has none — check `requirements.txt` for a dev section first; plain `requirements.txt` addition is acceptable)

```python
# tests/test_auth_claude.py
import time

import pytest
import respx
from httpx import Response
from cryptography.fernet import Fernet

import secretstore
from connections.auth import claude


@pytest.fixture()
def enc(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    return data_dir


def test_start_login_builds_pkce_url(enc):
    out = claude.start_login()
    assert out["flow"] == "paste-code"
    assert out["authUrl"].startswith(claude.AUTHORIZE_URL)
    assert "code_challenge=" in out["authUrl"] and "state=" in out["authUrl"]


@respx.mock
def test_complete_login_stores_tokens(enc):
    start = claude.start_login()
    state = start["authUrl"].split("state=")[1].split("&")[0]
    respx.post(claude.TOKEN_URL).mock(
        return_value=Response(200, json={
            "access_token": "at-1", "refresh_token": "rt-1",
            "expires_in": 3600, "scope": "user:inference",
        })
    )
    meta = claude.complete_login(f"authcode#{state}")
    rec = secretstore.get_connection("claude")["oauth"]
    assert rec["accessToken"] == "at-1" and rec["refreshToken"] == "rt-1"
    assert "accessToken" not in meta  # metadata only, no secrets


def test_complete_login_rejects_bad_state(enc):
    claude.start_login()
    with pytest.raises(claude.AuthError):
        claude.complete_login("authcode#wrong-state")


@respx.mock
def test_get_valid_token_refreshes_and_keeps_old_refresh_token(enc):
    secretstore.set_connection("claude", {"oauth": {
        "accessToken": "old", "refreshToken": "rt-keep",
        "expiresAt": time.time() + 10, "scope": "", "connectedAt": 0,
    }})
    respx.post(claude.TOKEN_URL).mock(
        return_value=Response(200, json={"access_token": "at-new", "expires_in": 3600})
    )
    assert claude.get_valid_access_token() == "at-new"
    rec = secretstore.get_connection("claude")["oauth"]
    assert rec["refreshToken"] == "rt-keep"  # omitted in response -> preserved


def test_get_valid_token_fresh_skips_refresh(enc):
    secretstore.set_connection("claude", {"oauth": {
        "accessToken": "still-good", "refreshToken": "r",
        "expiresAt": time.time() + 3600, "scope": "", "connectedAt": 0,
    }})
    assert claude.get_valid_access_token() == "still-good"


def test_get_valid_token_disconnected_raises(enc):
    with pytest.raises(claude.AuthError):
        claude.get_valid_access_token()
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_auth_claude.py -q` — FAIL

- [ ] **Step 3: Implement**

```python
# connections/auth/claude.py
"""Claude Pro/Max subscription OAuth (PKCE paste-code flow).

Ported from aether server/auth/claude.js. Reuses Claude Code's public OAuth
client. NOTE: undocumented by Anthropic and ToS-gray; subscription tokens
additionally require the Claude Code system preamble on every API call.
Pending PKCE state lives in module memory only — never persisted, never
sent to the client.
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
import time
from urllib.parse import urlencode

import httpx

# Verify every constant against aether server/auth/claude.js when porting.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPES = "org:create_api_key user:profile user:inference"
CLAUDE_CODE_PREAMBLE = "You are Claude Code, Anthropic's official CLI for Claude."

_EXPIRY_SKEW_S = 300


class AuthError(RuntimeError):
    """Login/refresh failed or the connection is absent."""


_pending: dict | None = None
_refresh_lock = threading.Lock()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def start_login() -> dict:
    global _pending
    verifier = _b64url(os.urandom(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = _b64url(os.urandom(16))
    _pending = {"verifier": verifier, "state": state}
    query = urlencode({
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return {"flow": "paste-code", "authUrl": f"{AUTHORIZE_URL}?{query}"}


def _store_record(payload: dict, old_refresh: str | None = None) -> dict:
    from secretstore import set_connection

    record = {
        "accessToken": payload["access_token"],
        "refreshToken": payload.get("refresh_token") or old_refresh or "",
        "expiresAt": time.time() + float(payload.get("expires_in", 3600)),
        "scope": payload.get("scope", ""),
        "connectedAt": time.time(),
    }
    set_connection("claude", {"oauth": record, "authMode": "subscription"})
    return record


def complete_login(code_state: str) -> dict:
    global _pending
    if _pending is None:
        raise AuthError("No login in progress. Start again.")
    code, _, state = code_state.strip().partition("#")
    if not code or state != _pending["state"]:
        raise AuthError("Pasted code doesn't match this login attempt. Start again.")
    resp = httpx.post(TOKEN_URL, json={
        "grant_type": "authorization_code",
        "code": code,
        "state": state,
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": _pending["verifier"],
    }, timeout=30)
    _pending = None
    if resp.status_code != 200:
        raise AuthError(f"Token exchange failed ({resp.status_code}).")
    record = _store_record(resp.json())
    return {"connectedAt": record["connectedAt"], "expiresAt": record["expiresAt"], "scope": record["scope"]}


def get_valid_access_token() -> str:
    from secretstore import get_connection

    with _refresh_lock:
        record = get_connection("claude").get("oauth")
        if not record or not record.get("accessToken"):
            raise AuthError("Claude subscription is not connected.")
        if record.get("expiresAt", 0) - time.time() > _EXPIRY_SKEW_S:
            return record["accessToken"]
        resp = httpx.post(TOKEN_URL, json={
            "grant_type": "refresh_token",
            "refresh_token": record.get("refreshToken", ""),
            "client_id": CLIENT_ID,
        }, timeout=30)
        if resp.status_code != 200:
            raise AuthError("Claude token refresh failed — reconnect the subscription in Settings.")
        return _store_record(resp.json(), old_refresh=record.get("refreshToken"))["accessToken"]
```

Add `respx` to `requirements.txt` (dev/test dependency; keep the pin style used by the file).

- [ ] **Step 4: Run** `python -m pytest tests/test_auth_claude.py -q` — PASS

- [ ] **Step 5: Commit**

```bash
git add connections/auth/ tests/test_auth_claude.py requirements.txt
git commit -m "feat: Claude subscription OAuth (PKCE paste-code) with lazy locked refresh"
```

---

### Task 6: AnthropicProvider OAuth mode

**Files:**
- Modify: `providers/anthropic_provider.py`
- Test: `tests/test_anthropic_oauth_mode.py`

**Interfaces:**
- Consumes: `connections.auth.claude.get_valid_access_token`, `CLAUDE_CODE_PREAMBLE`.
- Produces: `AnthropicProvider(model=None, api_key=None, oauth=False)`. In oauth mode: client built per call with `anthropic.Anthropic(auth_token=<fresh token>, default_headers={"anthropic-beta": "oauth-2025-04-20"})`; `complete()` sends `system` as blocks `[{"type": "text", "text": CLAUDE_CODE_PREAMBLE}, {"type": "text", "text": system}]`. Key mode unchanged.

- [ ] **Step 1: Write the failing tests** (mock the SDK — no network)

```python
# tests/test_anthropic_oauth_mode.py
from unittest.mock import MagicMock, patch

from connections.auth.claude import CLAUDE_CODE_PREAMBLE
from providers.anthropic_provider import AnthropicProvider


def _fake_anthropic(captured: dict):
    fake_sdk = MagicMock()

    def ctor(**kwargs):
        captured["ctor"] = kwargs
        client = MagicMock()
        block = MagicMock(type="text", text="pong")
        client.messages.create.side_effect = lambda **kw: (captured.update(create=kw), MagicMock(content=[block]))[1]
        return client

    fake_sdk.Anthropic.side_effect = ctor
    return fake_sdk


def test_oauth_mode_uses_bearer_beta_and_preamble(monkeypatch):
    captured: dict = {}
    with patch("connections.auth.claude.get_valid_access_token", return_value="tok-1"):
        provider = AnthropicProvider(model="claude-opus-4-8", oauth=True)
        provider._anthropic = _fake_anthropic(captured)
        assert provider.complete("do a thing", [{"role": "user", "content": "hi"}]) == "pong"
    assert captured["ctor"]["auth_token"] == "tok-1"
    assert captured["ctor"]["default_headers"] == {"anthropic-beta": "oauth-2025-04-20"}
    system = captured["create"]["system"]
    assert system[0] == {"type": "text", "text": CLAUDE_CODE_PREAMBLE}
    assert system[1] == {"type": "text", "text": "do a thing"}


def test_key_mode_unchanged(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    provider = AnthropicProvider()
    assert provider._oauth is False
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_anthropic_oauth_mode.py -q` — FAIL (`TypeError: unexpected keyword 'oauth'`)

- [ ] **Step 3: Implement** — rework `providers/anthropic_provider.py`:

```python
class AnthropicProvider(LLMProvider):
    def __init__(self, model: str | None = None, api_key: str | None = None, oauth: bool = False) -> None:
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover - import guard
            raise ProviderError(
                "The 'anthropic' package is required for the Anthropic provider."
            ) from exc
        self._anthropic = anthropic
        self._oauth = oauth
        if not oauth:
            key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise ProviderError("ANTHROPIC_API_KEY is not set.")
            self._client = anthropic.Anthropic(api_key=key)
        self._model = env_model("claude-opus-4-8", model)

    def _get_client(self):
        """Key mode: the cached client. OAuth mode: per-call client with a
        fresh subscription token (lazy refresh lives in the auth module)."""
        if not self._oauth:
            return self._client
        from connections.auth.claude import get_valid_access_token

        return self._anthropic.Anthropic(
            auth_token=get_valid_access_token(),
            default_headers={"anthropic-beta": "oauth-2025-04-20"},
        )

    def _system_param(self, system: str):
        if not self._oauth:
            return system
        from connections.auth.claude import CLAUDE_CODE_PREAMBLE

        # Subscription tokens are rejected unless this exact preamble is the
        # first system block.
        return [
            {"type": "text", "text": CLAUDE_CODE_PREAMBLE},
            {"type": "text", "text": system},
        ]
```

Then `list_models` and `complete` call `self._get_client()` instead of `self._client`, and `complete` passes `system=self._system_param(system)`. `extract_json` is unchanged (it funnels through `complete`).

- [ ] **Step 4: Run** `python -m pytest tests/test_anthropic_oauth_mode.py tests/ -q` — PASS

- [ ] **Step 5: Commit**

```bash
git add providers/anthropic_provider.py tests/test_anthropic_oauth_mode.py
git commit -m "feat: Anthropic provider OAuth mode (bearer + beta header + preamble)"
```

---

### Task 7: Provider factory — `get_provider(task)`, connection-built providers, OpenRouter

**Files:**
- Modify: `providers/__init__.py` (replace single `_cached` with a keyed cache and routing resolution), `providers/openai_provider.py` (add `base_url: str | None = None` ctor param, passed to `openai.OpenAI(...)` — read the file first; keep everything else unchanged)
- Test: `tests/test_provider_factory.py`

**Interfaces:**
- Produces: `get_provider(task: str | None = None, refresh: bool = False) -> LLMProvider`; `build_connection_provider(card: str, model: str | None) -> LLMProvider` (uncached, used by auth routes for validation/test/model-listing); `reset_provider() -> None` (clears the cache). Resolution ladder: `LLM_PROVIDER=fake` env short-circuit → `modelrouting.resolve(load(), task)` → `secretstore.legacy_default()` → `ProviderError`.
- Card → provider: `claude` → `AnthropicProvider(oauth=True)` when an oauth record exists and `authMode != "apikey"`, else `AnthropicProvider(api_key=...)`; `codex` → `OpenAIProvider(api_key=...)`; `openrouter` → `OpenAIProvider(api_key=..., base_url="https://openrouter.ai/api/v1")`; `ollama` → `OllamaProvider(host=conn["baseUrl"])`.
- All existing `get_provider()` no-arg call sites keep working (default resolution). Do NOT change call-site signatures in this task — per-task threading is Stage 2.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_provider_factory.py
import pytest
from cryptography.fernet import Fernet

import modelrouting
import secretstore
from modelrouting import Route, Routing
from providers import ProviderError, build_connection_provider, get_provider, reset_provider


@pytest.fixture(autouse=True)
def clean(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    for var in ("LLM_PROVIDER", "LLM_MODEL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    reset_provider()
    yield
    reset_provider()


def test_fake_env_short_circuit(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    from providers.fake import FakeProvider
    assert isinstance(get_provider(), FakeProvider)


def test_routing_default_selects_connection():
    secretstore.set_connection("claude", {"apiKey": "sk-ant-1", "authMode": "apikey"})
    modelrouting.save(Routing(default=Route("claude", "claude-opus-4-8")))
    provider = get_provider()
    assert type(provider).__name__ == "AnthropicProvider"
    assert provider._model == "claude-opus-4-8"


def test_task_route_beats_default():
    secretstore.set_connection("claude", {"apiKey": "sk-ant-1", "authMode": "apikey"})
    secretstore.set_connection("ollama", {"baseUrl": "http://box:11434"})
    modelrouting.save(Routing(
        tasks={"keywords": Route("ollama", "llama3.1")},
        default=Route("claude", ""),
    ))
    assert type(get_provider("keywords")).__name__ == "OllamaProvider"
    assert type(get_provider("tailor")).__name__ == "AnthropicProvider"


def test_legacy_env_fallback_without_routing(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai-1")
    assert type(get_provider()).__name__ == "OpenAIProvider"


def test_oauth_claude_when_record_present():
    import time
    secretstore.set_connection("claude", {
        "oauth": {"accessToken": "t", "refreshToken": "r", "expiresAt": time.time() + 3600},
        "authMode": "subscription",
    })
    provider = build_connection_provider("claude", None)
    assert provider._oauth is True


def test_openrouter_uses_base_url():
    secretstore.set_connection("openrouter", {"apiKey": "sk-or-1"})
    provider = build_connection_provider("openrouter", "openrouter/auto")
    assert type(provider).__name__ == "OpenAIProvider"


def test_unknown_card_raises():
    with pytest.raises(ProviderError):
        build_connection_provider("copilot", None)
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_provider_factory.py -q` — FAIL

- [ ] **Step 3: Implement** — replace the body of `providers/__init__.py` below the imports/docstring:

```python
__all__ = [
    "LLMProvider", "Message", "ProviderError",
    "build_connection_provider", "get_provider", "reset_provider",
]

_cache: dict[tuple[str, str | None], LLMProvider] = {}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def build_connection_provider(card: str, model: str | None) -> LLMProvider:
    """Build (uncached) a provider for a connection card. Raises ProviderError."""
    from secretstore import get_connection

    conn = get_connection(card)
    if card == "claude":
        from .anthropic_provider import AnthropicProvider

        if conn.get("oauth") and conn.get("authMode") != "apikey":
            return AnthropicProvider(model=model, oauth=True)
        return AnthropicProvider(model=model, api_key=conn.get("apiKey") or None)
    if card == "codex":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(model=model, api_key=conn.get("apiKey") or None)
    if card == "openrouter":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(
            model=model, api_key=conn.get("apiKey") or None, base_url=OPENROUTER_BASE_URL
        )
    if card == "ollama":
        from .ollama_provider import OllamaProvider

        return OllamaProvider(model=model, host=conn.get("baseUrl") or None)
    raise ProviderError(f"Unknown connection '{card}'.")


def get_provider(task: str | None = None, refresh: bool = False) -> LLMProvider:
    """Provider for a task via the routing ladder: task route -> default ->
    legacy env behavior. LLM_PROVIDER=fake short-circuits (tests)."""
    import os

    if os.environ.get("LLM_PROVIDER", "").strip().lower() == "fake":
        from .fake import FakeProvider

        return FakeProvider()

    import modelrouting

    route = modelrouting.resolve(modelrouting.load(), task)
    if route is not None:
        card, model = route.connection, (route.model or None)
    else:
        from secretstore import legacy_default

        card, model_str = legacy_default()
        model = model_str or None
        if card is None:
            raise ProviderError(
                "No model routing configured and LLM_PROVIDER is not one of "
                "anthropic, openai, ollama."
            )
    key = (card, model)
    if refresh:
        _cache.pop(key, None)
    if key not in _cache:
        _cache[key] = build_connection_provider(card, model)
    return _cache[key]


def reset_provider() -> None:
    """Clear all cached providers (called after settings writes and by tests)."""
    _cache.clear()
```

In `providers/openai_provider.py`: add `base_url: str | None = None` to `__init__` and pass it through to the `openai.OpenAI(...)` construction (only when not None, to preserve current behavior).

- [ ] **Step 4: Run the full backend suite** — `python -m pytest tests/ -q` — PASS (existing tests that relied on the old single cache still pass because `reset_provider()` and the fake short-circuit are preserved; fix any that construct `get_provider(refresh=True)` expecting the old semantics by reading them first)

- [ ] **Step 5: Commit**

```bash
git add providers/ tests/test_provider_factory.py
git commit -m "feat: routing-aware provider factory with per-connection cache"
```

---

### Task 8: Auth API — schemas + routes

**Files:**
- Modify: `api/schemas.py` (append), `api/routes.py` (append; also import `connections`, `modelrouting`)
- Test: `tests/test_auth_api.py`

**Interfaces:**
- Produces (schemas, all `_Camel`):

```python
class ConnectionStatus(_Camel):
    provider: str
    label: str
    modes: list[str]
    subscription_connected: bool = False
    api_key_connected: bool = False
    auth_mode: str = ""
    expires_at: float | None = None
    connected_at: float | None = None

class ConnectionList(_Camel):
    encryption_available: bool
    connections: list[ConnectionStatus] = []

class StartLoginResult(_Camel):
    flow: str
    auth_url: str | None = None
    user_code: str | None = None
    verification_uri: str | None = None

class CompleteLoginRequest(_Camel):
    code: str

class ApiKeyRequest(_Camel):
    api_key: str | None = None
    base_url: str | None = None
    bearer: str | None = None

class ConnectionTestRequest(_Camel):
    model: str | None = None
```

- Produces (routes; all sync `def`, matching the file's style):
  - `GET /api/auth/status` → `ConnectionList` (one `ConnectionStatus` per catalog card; `api_key_connected` true when `get_connection(card)` has `apiKey` — or `baseUrl` for ollama; `subscription_connected` true when an `oauth` record with an `accessToken` exists; never any token material)
  - `POST /api/auth/{provider}/start` → `StartLoginResult` (claude → `connections.auth.claude.start_login()`; any other provider → 400 "Subscription sign-in is not available for this provider yet.")
  - `POST /api/auth/claude/complete` body `CompleteLoginRequest` → `ConnectionStatus` for claude (an `AuthError` → 400 with its message)
  - `POST /api/auth/{provider}/key` body `ApiKeyRequest` → `ModelList`: build a probe provider via `providers.build_connection_provider` **after** temporarily applying the submitted key (validate-then-store: construct the provider directly with the submitted key/baseUrl — for claude/codex/openrouter pass `api_key=body.api_key`, for ollama `host=body.base_url`; on `list_models()` failure → 400 with the provider's message and nothing stored; on success `secretstore.set_connection(...)` with `authMode: "apikey"` for dual-mode cards, then `reset_provider()`, return the models). Empty `api_key` with a key already stored = keep it and just re-validate with the stored one.
  - `GET /api/auth/{provider}/models` → `ModelList` via `build_connection_provider(provider, None).list_models()` (errors → 400/502 mirroring the existing `/api/models` handler)
  - `POST /api/auth/{provider}/test` body `ConnectionTestRequest` → `TestResult`: `build_connection_provider(provider, body.model).complete("ping", [{"role": "user", "content": "ping"}])`, wrapped exactly like the existing `test_settings` handler
  - `POST /api/auth/{provider}/logout?mode=` → `ConnectionStatus`: `secretstore.clear_mode(provider, mode or "apikey")` + `reset_provider()`
  - All `{provider}` params validated against `connections.catalog.CARDS` → 404 otherwise.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_auth_api.py
import time

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import secretstore
from api.main import app


@pytest.fixture()
def client(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    from providers import reset_provider
    reset_provider()
    return TestClient(app)


def test_status_lists_cards_without_secrets(client):
    secretstore.set_connection("claude", {"apiKey": "sk-ant-1", "authMode": "apikey"})
    body = client.get("/api/auth/status").json()
    cards = {c["provider"]: c for c in body["connections"]}
    assert set(cards) == {"claude", "codex", "openrouter", "ollama"}
    assert cards["claude"]["apiKeyConnected"] is True
    assert "sk-ant-1" not in str(body)


def test_start_claude_login(client):
    body = client.post("/api/auth/claude/start").json()
    assert body["flow"] == "paste-code" and "authUrl" in body


def test_start_unsupported_provider_400(client):
    assert client.post("/api/auth/openrouter/start").status_code == 400


def test_unknown_provider_404(client):
    assert client.get("/api/auth/copilot/models").status_code == 404


def test_key_validation_failure_stores_nothing(client, monkeypatch):
    from providers import ProviderError

    def boom(card, model):
        raise ProviderError("bad key")

    monkeypatch.setattr("api.routes.build_connection_provider", boom)
    resp = client.post("/api/auth/codex/key", json={"apiKey": "sk-bad"})
    assert resp.status_code == 400
    assert "apiKey" not in secretstore.load_store().get("connections", {}).get("codex", {})


def test_logout_subscription_clears_oauth_only(client):
    secretstore.set_connection("claude", {
        "oauth": {"accessToken": "t", "expiresAt": time.time() + 100},
        "apiKey": "sk-keep",
    })
    body = client.post("/api/auth/claude/logout?mode=subscription").json()
    assert body["subscriptionConnected"] is False
    assert secretstore.get_connection("claude")["apiKey"] == "sk-keep"
```

Note for the key-validation test: the route must call the probe through a name that is monkeypatchable at `api.routes` — import `build_connection_provider` into `api/routes.py`'s namespace (matching how `get_provider` is imported there today), and route the `/key` probe through a small helper `_probe_key(card, body)` that constructs the provider directly with the submitted credential; the test patches the constructor boundary. Adjust the patch target to whatever the implementation actually imports — but keep it at module level so tests can patch it.

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_auth_api.py -q` — FAIL (404s)

- [ ] **Step 3: Implement** the schemas and routes per the Interfaces block. Route sketch for the two least obvious handlers:

```python
def _connection_status(card_key: str) -> ConnectionStatus:
    meta = catalog.card(card_key)
    conn = secrets_store.get_connection(card_key)
    oauth = conn.get("oauth") or {}
    has_key = bool(conn.get("apiKey")) or (card_key == "ollama" and bool(conn.get("baseUrl")))
    return ConnectionStatus(
        provider=card_key,
        label=meta["label"],
        modes=list(meta["modes"]),
        subscription_connected=bool(oauth.get("accessToken")),
        api_key_connected=has_key,
        auth_mode=conn.get("authMode", ""),
        expires_at=oauth.get("expiresAt"),
        connected_at=oauth.get("connectedAt"),
    )


@router.post("/auth/{provider}/key", response_model=ModelList)
def post_connection_key(provider: str, body: ApiKeyRequest) -> ModelList:
    _require_card(provider)  # 404 on unknown
    if not secrets_store.encryption_available():
        raise HTTPException(status_code=400, detail="Set ENCRYPTION_KEY in .env first.")
    try:
        models = _probe_key(provider, body)  # build provider w/ submitted (or kept) cred, list_models()
    except ProviderError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    updates: dict = {}
    if body.api_key:
        updates["apiKey"] = body.api_key
    if body.base_url:
        updates["baseUrl"] = body.base_url
    if body.bearer:
        updates["bearer"] = body.bearer
    if "subscription" in catalog.card(provider)["modes"]:
        updates["authMode"] = "apikey"
    if updates:
        secrets_store.set_connection(provider, updates)
    reset_provider()
    return ModelList(models=[ModelInfo(id=m["id"], label=m.get("label") or m["id"]) for m in models])
```

- [ ] **Step 4: Run** `python -m pytest tests/test_auth_api.py tests/ -q` — PASS

- [ ] **Step 5: Commit**

```bash
git add api/schemas.py api/routes.py tests/test_auth_api.py
git commit -m "feat: /api/auth connection routes (status, login, key, models, test, logout)"
```

---

### Task 9: Routing API

**Files:**
- Modify: `api/schemas.py`, `api/routes.py`
- Test: `tests/test_routing_api.py`

**Interfaces:**
- Produces (schemas): `RouteModel(_Camel)` (`connection: str`, `model: str = ""`), `RoutingModel(_Camel)` (`tasks: dict[str, RouteModel] = {}`, `agent: RouteModel | None = None`, `default: RouteModel | None = None`), `RoutingUpdate(_Camel)` (same fields, all optional).
- Produces (routes): `GET /api/routing` → `RoutingModel`; `PUT /api/routing` body `RoutingUpdate` → merge only sent fields onto the stored routing (the `put_agent_config` `exclude_unset` pattern), validate every `connection` against the catalog (400 on unknown), `modelrouting.save(...)`, `reset_provider()`, return fresh `RoutingModel`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_routing_api.py
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def test_get_empty_routing(client):
    body = client.get("/api/routing").json()
    assert body == {"tasks": {}, "agent": None, "default": None}


def test_put_partial_update_merges(client):
    client.put("/api/routing", json={"default": {"connection": "claude", "model": "m1"}})
    client.put("/api/routing", json={"tasks": {"keywords": {"connection": "ollama", "model": "llama3.1"}}})
    body = client.get("/api/routing").json()
    assert body["default"]["connection"] == "claude"          # survived second PUT
    assert body["tasks"]["keywords"]["model"] == "llama3.1"


def test_put_unknown_connection_400(client):
    resp = client.put("/api/routing", json={"default": {"connection": "copilot"}})
    assert resp.status_code == 400


def test_put_unknown_task_ignored(client):
    client.put("/api/routing", json={"tasks": {"nonsense": {"connection": "claude"}}})
    assert client.get("/api/routing").json()["tasks"] == {}
```

- [ ] **Step 2: Run to verify failure** — FAIL (404)

- [ ] **Step 3: Implement** per Interfaces (validation walks every route in the payload through `connections.catalog.CARDS`; unknown task names are dropped by `Routing.from_dict` already).

- [ ] **Step 4: Run** `python -m pytest tests/test_routing_api.py -q` — PASS

- [ ] **Step 5: Commit**

```bash
git add api/schemas.py api/routes.py tests/test_routing_api.py
git commit -m "feat: GET/PUT /api/routing"
```

---

### Task 10: Rework legacy `/api/settings` surface onto v2 (deprecation shim)

**Files:**
- Modify: `api/routes.py` (`_settings_status`, `post_settings`, `_provider_from_update`, `test_settings`, `list_models`), `secretstore/__init__.py` (delete `resolve_credentials` once no caller remains)
- Test: modify `tests/test_settings_api.py` (read it fully first; keep every test that encodes preserved behavior, update ones that assert v1 internals)

**Interfaces:**
- `GET /api/settings` keeps its `SettingsStatus` wire shape, now derived from v2: `active_provider` = routing default's card mapped back (`claude`→`anthropic`, `codex`→`openai`, `ollama`→`ollama`; fall back to `legacy_default()`), `model` = routing default's model (or legacy), `anthropic_key_set` = `bool(get_connection("claude").get("apiKey"))`, `openai_key_set` likewise for `codex`, `ollama_host` from `get_connection("ollama")["baseUrl"]`.
- `POST /api/settings` (old single-provider shape) is a shim: map `active_provider` → card, write `api_key`/`ollama_host` into that connection via `set_connection`, write `{connection, model}` into `modelrouting` default, `reset_provider()`. Existing semantics preserved: empty key keeps stored; 400 without encryption.
- `_provider_from_update` / `/api/models` / `/api/settings/test`: rebuild on `build_connection_provider` + the card mapping; typed-but-unsaved key still works (construct directly with the submitted key).
- After this task `secretstore.resolve_credentials` has zero callers — delete it (grep to confirm: `grep -rn resolve_credentials --include='*.py' .` must return nothing before committing).

- [ ] **Step 1: Read `tests/test_settings_api.py` in full; write/adjust tests** asserting: old POST shape still saves a key and sets the default route; GET reflects v2 store; empty-key-keeps-existing still holds; `/api/models` works with a typed unsaved key. (Concrete assertions depend on the existing file — keep its fixtures and FakeProvider patching style.)

- [ ] **Step 2: Run to verify the new/changed tests fail** — `python -m pytest tests/test_settings_api.py -q`

- [ ] **Step 3: Implement** per Interfaces.

- [ ] **Step 4: Run the whole backend suite** — `python -m pytest tests/ -q` — PASS

- [ ] **Step 5: Commit**

```bash
git add api/routes.py secretstore/__init__.py tests/test_settings_api.py
git commit -m "refactor: legacy /api/settings backed by v2 connections; drop resolve_credentials"
```

---

### Task 11: Frontend API types + client functions

**Files:**
- Modify: `web/src/api/types.ts`, `web/src/api/client.ts`
- Test: type-check only (`npm run build` in `web/`) — these are declarations + thin fetch wrappers over the tested `request<T>` helper.

**Interfaces (produces):**

```typescript
// types.ts additions
export type CardKey = "claude" | "codex" | "openrouter" | "ollama";

export interface ConnectionStatus {
  provider: CardKey | string;
  label: string;
  modes: string[];
  subscriptionConnected: boolean;
  apiKeyConnected: boolean;
  authMode: string;
  expiresAt: number | null;
  connectedAt: number | null;
}

export interface ConnectionList {
  encryptionAvailable: boolean;
  connections: ConnectionStatus[];
}

export interface StartLoginResult {
  flow: "paste-code" | "browser" | "device-code" | string;
  authUrl?: string | null;
  userCode?: string | null;
  verificationUri?: string | null;
}

export interface RouteChoice { connection: string; model: string; }

export interface Routing {
  tasks: Record<string, RouteChoice>;
  agent: RouteChoice | null;
  default: RouteChoice | null;
}
```

```typescript
// client.ts additions (all via the existing request<T> helper)
export function listConnections(): Promise<ConnectionList> {
  return request("/api/auth/status");
}
export function startLogin(provider: string): Promise<StartLoginResult> {
  return request(`/api/auth/${provider}/start`, { method: "POST" });
}
export function completeClaudeLogin(code: string): Promise<ConnectionStatus> {
  return request("/api/auth/claude/complete", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
}
export function saveConnectionKey(
  provider: string,
  body: { apiKey?: string; baseUrl?: string; bearer?: string },
): Promise<ModelInfo[]> {
  return request<ModelList>(`/api/auth/${provider}/key`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.models);
}
export function listConnectionModels(provider: string): Promise<ModelInfo[]> {
  return request<ModelList>(`/api/auth/${provider}/models`).then((r) => r.models);
}
export function testConnectionProvider(provider: string, model?: string): Promise<TestResult> {
  return request(`/api/auth/${provider}/test`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: model || undefined }),
  });
}
export function logoutConnection(provider: string, mode: string): Promise<ConnectionStatus> {
  return request(`/api/auth/${provider}/logout?mode=${encodeURIComponent(mode)}`, { method: "POST" });
}
export function getRouting(): Promise<Routing> {
  return request("/api/routing");
}
export function updateRouting(body: Partial<Routing>): Promise<Routing> {
  return request("/api/routing", {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
```

(Match the exact `request` call style used by the existing functions in `client.ts` — read them before writing.)

- [ ] **Step 1: Implement the additions**
- [ ] **Step 2: Verify** — `cd web && npm run build` — Expected: compiles clean
- [ ] **Step 3: Commit**

```bash
git add web/src/api/types.ts web/src/api/client.ts
git commit -m "feat(web): API client for connections and routing"
```

---

### Task 12: Accounts UI section

**Files:**
- Create: `web/src/settings/AccountsSection.tsx`
- Test: `web/src/settings/AccountsSection.test.tsx`

**Interfaces:**
- Consumes: Task 11 client functions.
- Produces: `export function AccountsSection({ list, onChanged }: { list: ConnectionList; onChanged: () => void })` — renders one card per `list.connections` entry. Per card:
  - Status line: "Subscription connected" / "API key saved" / "Not connected" (both can show at once, aether-style).
  - Dual-mode cards (`modes` includes both): a `ToggleButtonGroup` Subscription | API key writing nothing until an action is taken.
  - Subscription connect (claude): button → `startLogin("claude")` → render the `authUrl` as an external link ("Open Anthropic sign-in") + a `TextField` for the pasted `code#state` + Confirm button → `completeClaudeLogin`, then `onChanged()`. Errors from the API render in an `Alert severity="error"` on the card.
  - API key / URL entry: `TextField type="password"` (or text for ollama base URL + optional bearer) with the existing placeholder convention ("•••••  key saved" when `apiKeyConnected`), Save button → `saveConnectionKey`, then `onChanged()`; empty input = keep existing (send `{}` → backend revalidates stored key).
  - Disconnect per mode: button → `logoutConnection(provider, mode)` → `onChanged()`.
  - Use `SettingsSection`, `ButtonSpinner`, `Alert` exactly as `SettingsModal.tsx` does today. Keep the component under ~250 lines; extract a `ConnectionCard` child component in the same file.

- [ ] **Step 1: Write the failing tests** (vitest + testing-library, mocking `../api/client` — mirror the mocking style in `web/src/settings/SettingsModal.test.tsx`, read it first)

```tsx
// web/src/settings/AccountsSection.test.tsx — core cases:
// 1. renders one card per connection with its label
// 2. claude card: clicking "Connect" calls startLogin and shows the paste field
//    when the mocked result is {flow: "paste-code", authUrl: "https://x"}
// 3. submitting a pasted code calls completeClaudeLogin("code#state") and fires onChanged
// 4. saving a key calls saveConnectionKey("codex", {apiKey: "sk-x"}) and fires onChanged
// 5. a rejected saveConnectionKey renders its message in an Alert
// 6. disconnect button calls logoutConnection with the card's mode
```

Write these as real tests against the mocked client module; assert with `screen.findByText`/`getByLabelText` and `vi.mocked(...)` call args.

- [ ] **Step 2: Run to verify failure** — `cd web && npm test -- AccountsSection` — FAIL
- [ ] **Step 3: Implement `AccountsSection.tsx`** per the Interfaces block.
- [ ] **Step 4: Run** — `cd web && npm test -- AccountsSection` — PASS
- [ ] **Step 5: Commit**

```bash
git add web/src/settings/AccountsSection.*
git commit -m "feat(web): provider accounts section (subscription + API key flows)"
```

---

### Task 13: Default-model section + SettingsModal rewire

**Files:**
- Create: `web/src/settings/DefaultModelSection.tsx`
- Modify: `web/src/settings/SettingsModal.tsx` (replace the Provider section with `<AccountsSection>` + `<DefaultModelSection>`; drop `buildUpdate`/`saveSettings`/`testConnection` usage; keep the encryption-off warning `Alert` at the top)
- Test: `web/src/settings/DefaultModelSection.test.tsx`; update `web/src/settings/SettingsModal.test.tsx`

**Interfaces:**
- `DefaultModelSection({ connections, routing, onSaved }: { connections: ConnectionStatus[]; routing: Routing; onSaved: (r: Routing) => void })`:
  - Connection select (connected cards only: `subscriptionConnected || apiKeyConnected`), model select fed by `listConnectionModels(card)` with the existing `CUSTOM_MODEL` free-text escape hatch and Reload button pattern (copy the pattern from the current modal, lines 283–346).
  - Save → `updateRouting({ default: { connection, model } })` → `onSaved`. Test button → `testConnectionProvider(connection, model)` rendering `TestResult` in the existing ok/fail `Alert` pattern.
- `SettingsModal` loads `listConnections()` + `getRouting()` on open, holds them in state, passes them down; `onChanged` refetches connections; `onSaved` replaces routing state. Dialog title/actions unchanged except the old Save/Test buttons move into `DefaultModelSection`.

- [ ] **Step 1: Write the failing tests** — `DefaultModelSection.test.tsx`: connection select lists only connected cards; choosing a connection loads its models; Save calls `updateRouting` with `{default: {connection, model}}`; Test renders the mocked `TestResult.detail`. Update `SettingsModal.test.tsx` to mock `listConnections`/`getRouting` and assert both sections render.
- [ ] **Step 2: Run to verify failure** — `cd web && npm test` — FAIL
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run all frontend tests and build** — `cd web && npm test && npm run build` — PASS
- [ ] **Step 5: Commit**

```bash
git add web/src/settings/
git commit -m "feat(web): default model routing section; settings modal on connections API"
```

---

### Task 14: Docs + env surface

**Files:**
- Modify: `README.md` (Configuration table: note that provider accounts are configured in Settings → Accounts; env vars remain as fallback), `.env.example` (same note as comments; no new vars in Stage 1), `docs/reference/api.md` (add the `/api/auth/*` and `/api/routing` routes beside the existing settings routes)
- Do NOT hand-edit any `<!-- generated:start -->` block (`docs/conventions/agent-workflow.md` step 6).

- [ ] **Step 1: Make the edits** (plain factual descriptions of current behavior; no migration narration in reference docs)
- [ ] **Step 2: Verify** — `python -m pytest tests/ -q` and `cd web && npm run build` one final time
- [ ] **Step 3: Commit**

```bash
git add README.md .env.example docs/reference/api.md
git commit -m "docs: connection accounts + routing API reference"
```

---

## Deferred to later stages (named blockers, not preferences)

- **Stage 2 — per-task routing UI + agent wiring** (`/api/agent/llm-credentials` + `X-Agent-Token` guard + `daily-apply.sh` + Agents-page Model section + threading task names into the six `get_provider()` call sites): blocked on this stage's `modelrouting`/factory interfaces landing as implemented, since its plan must quote their real signatures. Unblocked the moment Stage 1 merges.
- **Stage 3 — Codex/Copilot/Antigravity OAuth + their providers + OpenRouter model discovery hardening + catalog additions + compose port 1455**: blocked on the same interfaces plus the Stage 1 auth-module pattern (`connections/auth/claude.py`) being the template it copies.

## Self-review notes

- Spec coverage: catalog ✔ (Task 1), v2 store + migration + `.bak` + idempotency + env fallback ✔ (2–3), routing store ✔ (4), Claude OAuth + preamble/beta/bearer ✔ (5–6), factory + OpenRouter ✔ (7), auth routes + validate-then-store + never-secrets ✔ (8), routing routes ✔ (9), legacy shim + empty-key-keeps ✔ (10), UI ✔ (11–13), docs ✔ (14). Copilot/Antigravity/Codex-OAuth/agent-wiring are explicitly staged out with blockers above.
- Type consistency: `Route/Routing` names match across Tasks 4/7/9; `build_connection_provider` matches across 7/8/10; `ConnectionStatus` fields match across 8/11/12.
- The `code: "true"` authorize param in Task 5 is flagged for verification against aether's source at port time (the task instructs verifying every constant against `server/auth/claude.js`).
