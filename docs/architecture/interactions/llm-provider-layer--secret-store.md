<!-- generated:start edge:llm-provider-layer→secret-store -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: LLM Provider Layer → Secret Store

- **Participants:** `llm-provider-layer` → `secret-store`
- **Transport:** `in-process`
<!-- generated:end edge:llm-provider-layer→secret-store -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The LLM Provider Layer calls exactly one function on the Secret Store: `resolve_credentials() -> dict`. There is no network protocol — it is a synchronous in-process Python call (`from secretstore import resolve_credentials`).

**Response shape** — `resolve_credentials()` always returns a `dict` containing every key in `secretstore._FIELDS`:

| Key | Type | Meaning / default |
|-----|------|-------------------|
| `activeProvider` | `str` | selects the provider; env default `LLM_PROVIDER` or `"anthropic"` |
| `anthropicApiKey` | `str` | env default `ANTHROPIC_API_KEY` or `""` |
| `openaiApiKey` | `str` | env default `OPENAI_API_KEY` or `""` |
| `ollamaHost` | `str` | env default `OLLAMA_HOST` or `"http://localhost:11434"` |
| `model` | `str` | env default `LLM_MODEL` or `""` |

**Invariants:**
- All five keys are always present; missing/absent secrets never produce a `KeyError`, only empty strings/defaults.
- Resolution order is `secrets.enc` over environment: a stored value wins only if truthy (`if v:` in `resolve_credentials`), otherwise the env/default is used.
- `read_secrets()` returns `{}` (never raises) when encryption is unavailable, the blob is absent, or the ciphertext is corrupt/foreign — so a decrypt failure degrades gracefully to env-based credentials.
- The provider layer treats empty strings as "unset": in `get_provider`, `creds["model"] or None` and `creds["anthropicApiKey"] or None` convert `""` to `None` before passing to constructors.
- The Secret Store never returns a live provider or validates keys; it only merges credential strings. Validation ("key is not set", request failures) happens inside each concrete provider constructor.

The write side (`write_secrets`, exposed via the API's `/settings` routes, not the provider layer) filters to `_FIELDS`, drops `None` values, and raises `SecretsUnavailable` when `ENCRYPTION_KEY` is missing/invalid.

## Auth  (how the interaction is authenticated)

There is **no authentication between the two components** — they run in the same process and the provider layer imports the Secret Store directly as a downward (leaf) dependency. The Secret Store exists specifically to break an import cycle (providers must not import `api`), per its module docstring.

Authentication is instead about the *secrets themselves*:
- The encrypted secrets blob (`data/secrets.enc`) is protected by a **Fernet symmetric key** read from the `ENCRYPTION_KEY` environment variable (`secretstore.encryption_key()` / `_fernet()`).
- If `ENCRYPTION_KEY` is unset or invalid, `_fernet()` returns `None`; encryption is silently disabled and credentials fall back to environment variables. Writes are then rejected with `SecretsUnavailable`.
- The credentials the Secret Store resolves (`anthropicApiKey`, `openaiApiKey`) are the actual auth material each provider uses against its upstream API — e.g. `anthropic.Anthropic(api_key=key)` and `openai.OpenAI(api_key=key)`. Ollama uses an unauthenticated host URL.

## Flow  (the sequence of the interaction)

1. An API route (e.g. `/api/extract`, `/api/tailor`, `/api/cover-letter`, `/api/settings/test`) calls `get_provider()` in `providers/__init__.py`.
2. If a provider instance is already cached (`_cached`) and `refresh` is `False`, it is returned immediately — the Secret Store is **not** consulted.
3. Otherwise `get_provider` calls `secretstore.resolve_credentials()`.
4. `resolve_credentials()` calls `read_secrets()`, which builds a Fernet from `ENCRYPTION_KEY`, reads `data/secrets.enc` (path from `truth.store.data_dir()`), decrypts and JSON-parses it — or returns `{}` on any failure.
5. `resolve_credentials()` seeds a dict from environment variables/defaults, then overlays each truthy stored value, and returns the merged dict.
6. `get_provider` reads `activeProvider` and `model`, then instantiates the matching concrete provider (`AnthropicProvider` / `OpenAIProvider` / `OllamaProvider` / `FakeProvider`), passing the relevant credential (`api_key` or `host`). An unknown provider raises `ProviderError`.
7. The provider is cached in `_cached` and returned. Concrete constructors validate the credential (raising `ProviderError` if a required key is missing).
8. On a settings change, `POST /api/settings` calls `write_secrets(...)` then `reset_provider()`, clearing `_cached` so the next `get_provider()` re-runs the resolution flow with the new secrets.

Note: individual providers also read env vars directly as a fallback (e.g. `os.environ.get("ANTHROPIC_API_KEY")`), but the primary path supplies credentials via the Secret Store.

## Code  (entry points on both sides, with file paths)

**Secret Store side (`secretstore/__init__.py`):**
- `resolve_credentials()` — the single entry point the provider layer calls; merges secrets over env.
- `read_secrets()` — decrypts `secrets.enc` (Fernet), returns `{}` on any failure.
- `write_secrets(data)` — encrypts and atomically persists (used by API settings routes, not the provider layer); raises `SecretsUnavailable` without a valid key.
- `encryption_available()` / `encryption_key()` / `_fernet()` / `secrets_path()` — key handling and blob location (`truth.store.data_dir() / "secrets.enc"`).
- `SecretsUnavailable` — raised on writes without a valid `ENCRYPTION_KEY`.
- `_FIELDS` — the fixed set of credential keys.

**LLM Provider Layer side:**
- `providers/__init__.py` — `get_provider(refresh=False)`: imports and calls `secretstore.resolve_credentials()`, selects and caches the provider; `reset_provider()` clears the cache.
- `providers/base.py` — `LLMProvider` ABC (`complete`, `extract_json`, `list_models`), `ProviderError`, `env_model()`.
- `providers/anthropic_provider.py` — `AnthropicProvider(model, api_key)`; consumes `anthropicApiKey`.
- `providers/openai_provider.py` — `OpenAIProvider(model, api_key)`; consumes `openaiApiKey`.
- `providers/ollama_provider.py` — `OllamaProvider(model, host)`; consumes `ollamaHost`.
- `providers/fake.py` — `FakeProvider` (test/`activeProvider="fake"` path).

**Callers / adjacent glue:**
- `api/routes.py` — invokes `get_provider()` (`/extract`, `/tailor`, `/cover-letter`, `/settings/test`) and `secrets_store.resolve_credentials()` / `read_secrets()` / `write_secrets()` (`/settings`, `/settings/test`, `/models`); calls `reset_provider()` after a settings write.
- `api/secrets.py` — backwards-compatible shim re-exporting the `secretstore` API for `api`-side callers.
