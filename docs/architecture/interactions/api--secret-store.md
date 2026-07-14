<!-- generated:start edge:api→secret-store -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: API → Secret Store

- **Participants:** `api` → `secret-store`
- **Transport:** `in-process`
<!-- generated:end edge:api→secret-store -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Secret Store (`secretstore`) is an **in-process Python library**, not a network service — the API calls its functions directly (there is no wire protocol between them). Its contract is the module's public function surface (`secretstore/__init__.py`):

- `resolve_credentials() -> dict` — always returns every field in `_FIELDS` = `("activeProvider", "anthropicApiKey", "openaiApiKey", "ollamaHost", "model")`. Values are merged: a non-empty `secrets.enc` value wins, else the corresponding env var (`LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_HOST`, `LLM_MODEL`), else a default (`activeProvider="anthropic"`, `ollamaHost="http://localhost:11434"`, keys/model `""`). Never raises.
- `read_secrets() -> dict` — returns the decrypted stored dict, or `{}` if the key is unavailable, the file is absent, or the blob is corrupt/foreign. Never raises.
- `write_secrets(data: dict) -> None` — filters `data` to keys in `_FIELDS` (dropping `None` values), encrypts, and writes atomically (temp file → `replace`). Raises `SecretsUnavailable` when no valid `ENCRYPTION_KEY` is set.
- `encryption_available() -> bool` — True iff a valid Fernet key is present.
- `SecretsUnavailable(RuntimeError)` — write-only failure signal.

**Invariants:**
- Resolution order is fixed: `secrets.enc` (only if key valid) → environment → default.
- Only `secrets.enc` is encrypted; a missing/invalid `ENCRYPTION_KEY` degrades gracefully to env-only, read-only mode (writes fail, reads return `{}`).
- Reads never crash on a bad/foreign/corrupt blob — it is treated as absent.
- Writes are whitelisted (`_FIELDS`) and atomic.

The API surfaces this over HTTP via `SettingsStatus` / `SettingsUpdate` schemas (`api/schemas.py`), using camelCase JSON aliases. `SettingsStatus` deliberately exposes only booleans for key presence (`anthropic_key_set`, `openai_key_set`) — **never the raw key values** — plus `encryption_available`, `active_provider`, `model`, and `ollama_host`.

## Auth  (how the interaction is authenticated)

There is **no authentication between the API and the Secret Store** — it is a direct in-process function call within the same Python process, so no credentials cross a boundary.

The store's own protection is **encryption at rest**, not authentication:
- Confidentiality/integrity of `secrets.enc` comes from a Fernet symmetric key read from the `ENCRYPTION_KEY` environment variable (`encryption_key()` in `secretstore/__init__.py`). A key can be generated via `python -m api.genkey` (`api/genkey.py`, `Fernet.generate_key()`).
- Without a valid key, decryption/encryption is disabled: reads fall back to env vars and writes raise `SecretsUnavailable`.

The HTTP API layer that fronts the store (`api/main.py`) enforces **no auth of its own** — no API key, token, or session check on the settings routes. Its only access controls are CORS (`CORS_ORIGINS`, default `http://localhost:5173`) and path-traversal guards on the download route. The `/api/settings` POST additionally gates *writes* on `encryption_available()`, returning HTTP 400 (`"Set ENCRYPTION_KEY in .env first."`) rather than any authentication check.

## Flow  (the sequence of the interaction)

**Read settings — `GET /api/settings`** (`get_settings` → `_settings_status` in `api/routes.py`):
1. Calls `secrets_store.resolve_credentials()` and `secrets_store.encryption_available()`.
2. The store reads/decrypts `secrets.enc` (if a valid key exists), merges over env defaults.
3. API maps the result into `SettingsStatus`, exposing keys only as `*_key_set` booleans.

**Write settings — `POST /api/settings`** (`post_settings`):
1. If `encryption_available()` is False → HTTP 400 (no write attempted).
2. `read_secrets()` loads the current stored dict.
3. API mutates it in memory: sets `activeProvider`; sets `model`/`ollamaHost` if provided; if `api_key` is non-empty, routes it into `anthropicApiKey` or `openaiApiKey` based on `active_provider` (empty key leaves the stored key unchanged).
4. `write_secrets(current)` encrypts and atomically persists.
5. API calls `providers.reset_provider()` to invalidate the cached provider, then returns fresh `SettingsStatus` via `_settings_status()` (another `resolve_credentials()` round-trip).

**Test / list models — `POST /api/settings/test`, `POST /api/models`** (`test_settings`, `list_models` → `_provider_from_update`):
- `test_settings` calls `post_settings` (persisting), then instantiates a live provider and pings it.
- `_provider_from_update` calls `resolve_credentials()` and builds a provider from the submitted form value *or* the resolved stored credential — **without persisting** — so a dropdown/test can use an unsaved key.

**Credential consumption:** other providers/routes obtain resolved credentials from the same store (`resolve_credentials()`), which is why the store lives in the neutral `secretstore` package — so the provider layer can depend on it downward without importing `api`.

**Persistence location:** `secrets_path()` = `truth.store.data_dir() / "secrets.enc"`, where `data_dir()` is `DATA_DIR` (default `./data`), created on demand.

## Code  (entry points on both sides, with file paths)

**Secret Store side:**
- `secretstore/__init__.py` — the entire implementation: `resolve_credentials`, `read_secrets`, `write_secrets`, `encryption_available`, `encryption_key`, `secrets_path`, `_fernet`, `_FIELDS`, and the `SecretsUnavailable` exception.

**API side:**
- `api/secrets.py` — backwards-compatible shim re-exporting the `secretstore` symbols (imported in routes as `from api import secrets as secrets_store`).
- `api/config.py` — re-exports `encryption_key`, `secrets_path` from `secretstore`; also `profile_pdf_path`.
- `api/routes.py` — HTTP entry points that call the store:
  - `_settings_status()` (helper) — uses `resolve_credentials()`, `encryption_available()`.
  - `get_settings` (`GET /api/settings`)
  - `post_settings` (`POST /api/settings`) — uses `encryption_available`, `read_secrets`, `write_secrets`.
  - `test_settings` (`POST /api/settings/test`)
  - `_provider_from_update` + `list_models` (`POST /api/models`) — uses `resolve_credentials()`.
- `api/schemas.py` — `SettingsStatus`, `SettingsUpdate`, `TestResult`, `ModelList`/`ModelInfo` wire models.
- `api/main.py` — FastAPI app that mounts the router (CORS-only middleware; no auth).
- `api/genkey.py` — `python -m api.genkey` generates a Fernet `ENCRYPTION_KEY`.

**Supporting:**
- `truth/store.py` — `data_dir()`, which resolves the volume where `secrets.enc` is stored.
