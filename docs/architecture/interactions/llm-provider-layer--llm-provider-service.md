<!-- generated:start edge:llm-provider-layer→llm-provider-service -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: LLM Provider Layer → LLM Provider Service

- **Participants:** `llm-provider-layer` → `llm-provider-service`
- **Transport:** `HTTPS`
<!-- generated:end edge:llm-provider-layer→llm-provider-service -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The **provider layer** exposes one narrow interface, `LLMProvider` (`providers/base.py`), that all callers use; each concrete implementation translates those calls into a **provider-service** (external LLM API) request and normalizes the response back.

**Layer-facing contract (`LLMProvider`):**
- `complete(system: str, messages: list[dict[str,str]]) -> str` — returns plain text. Each message is `{"role": "system"|"user"|"assistant", "content": str}` (`Message.as_dict` / `to_messages` normalize `Message` objects or raw dicts to this shape).
- `extract_json(system, messages, schema: dict) -> dict` — returns a JSON **object** (a `dict`) that is asked to conform to the JSON-Schema `schema`. The schema is stringified and appended to the system prompt as an instruction; the raw text response is coerced to a dict by `parse_json_object` (`providers/_json.py`), which accepts a bare object, a fenced ```json block, or the first balanced `{...}` span, and raises `ProviderError` if none parse.
- `list_models() -> list[dict[str,str]]` — returns `[{"id","label"}, ...]`; default is `[]`.

**Service-facing request/response shapes:**
- *Anthropic* (`providers/anthropic_provider.py`): `client.messages.create(model, max_tokens=MAX_OUTPUT_TOKENS(=16000), thinking={"type":"disabled"}, system, messages)`; response is the concatenation of `block.text` for text blocks. `list_models` iterates `client.models.list()`.
- *OpenAI* (`providers/openai_provider.py`): `client.chat.completions.create(model, messages=[{"role":"system",...}, *messages], response_format={"type":"json_object"}` when JSON mode`)`; intentionally **no** `max_tokens`. Response is `choices[0].message.content or ""`. `list_models` filters `models.list().data` to `gpt-*` / `o\d` ids.
- *Ollama* (`providers/ollama_provider.py`): HTTP `POST {host}/api/chat` with `{model, messages, stream:false, options:{num_predict:16000}, format:"json"?}`, 120 s timeout; response is `json()["message"]["content"]`. `list_models` calls `GET {host}/api/tags`.

**Invariants:**
- Provider output is untrusted — comments in `providers/base.py` state nothing a provider returns is trusted until it passes the truth store and deterministic guardrail; no truthfulness logic may depend on the concrete provider.
- `MAX_OUTPUT_TOKENS = 16000` is a ceiling to avoid truncating long JSON extractions mid-array (OpenAI deliberately left uncapped so the o-series isn't broken).
- Model id resolution (`env_model`): explicit override → `LLM_MODEL` (empty/whitespace ignored) → per-provider default (`claude-opus-4-8`, `gpt-4o`, `llama3.1`).
- Any misconfiguration or call failure surfaces as `ProviderError` (a `RuntimeError`).

## Auth  (how the interaction is authenticated)

Credentials are resolved by the neutral `secretstore` package, never from the API layer, to avoid an import cycle (`providers/__init__.py`, `secretstore/__init__.py`).

- `secretstore.resolve_credentials()` merges the encrypted `secrets.enc` blob **over** environment defaults for the fields `activeProvider`, `anthropicApiKey`, `openaiApiKey`, `ollamaHost`, `model`. Stored (Fernet-decrypted via `ENCRYPTION_KEY`) values win where present; otherwise env vars (`LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_HOST`, `LLM_MODEL`) are used. A missing/invalid `ENCRYPTION_KEY` disables encryption gracefully and falls back to env vars.
- `get_provider()` reads `activeProvider` and passes the matching key into the concrete provider constructor.
- **Anthropic / OpenAI:** the API key is passed as `api_key` to the SDK client (`anthropic.Anthropic(api_key=key)` / `openai.OpenAI(api_key=key)`); the SDK sends it to the external service as a bearer/API-key header. If neither the injected key nor the corresponding env var is set, the constructor raises `ProviderError`.
- **Ollama:** no auth — only a `host` URL (default `http://localhost:11434`); it is local/offline.
- The end-user authenticates to the *layer* implicitly by saving settings: `POST /api/settings` writes the key into `secrets.enc` (requires `encryption_available()`), and `reset_provider()` clears the cache so the next `get_provider()` picks up new credentials.

## Flow  (the sequence of the interaction)

1. An API route (e.g. `POST /api/extract`, `/api/tailor`, `/api/cover-letter`) calls `get_provider()` (`api/routes.py`).
2. `get_provider()` (`providers/__init__.py`) returns a cached `LLMProvider`, or on first call/`refresh=True` calls `resolve_credentials()`, reads `activeProvider`, and instantiates the matching concrete provider (importing the SDK lazily and validating the key). Unknown provider → `ProviderError`.
3. A domain module builds a system prompt + messages (+ schema) and calls `provider.complete(...)` or `provider.extract_json(...)` — e.g. `truth/extract.py` (`build_truth_from_text` → `extract_json` with `_EXTRACTION_SCHEMA`), `tailor/*.py`, `coverletter/generate.py`.
4. The concrete provider serializes the request and calls the **external service**: Anthropic/OpenAI SDK client, or an `httpx.post` to the Ollama host.
5. The service returns; the provider extracts the text (or parses a JSON object via `parse_json_object`) and returns it up through the interface. HTTP/SDK errors become `ProviderError` (Ollama) or propagate.
6. The route wraps failures: `ProviderError` and generic exceptions become HTTP `502` ("The language model call failed…"); returned data flows onward to the truth store / guardrail, never trusted directly.

**Auxiliary flows:**
- **Test connection** (`POST /api/settings/test`): persists settings, `get_provider(refresh=True)`, then a `provider.complete("ping", …)` round-trip; returns `TestResult(ok, detail)`.
- **Model discovery** (`POST /api/models`): `_provider_from_update` builds a provider from submitted-or-saved credentials *without persisting*, then calls `provider.list_models()` → returns `ModelList`.

## Code  (entry points on both sides, with file paths)

**Provider-layer side (`providers/` package — the abstraction/consumers):**
- `providers/__init__.py` — `get_provider(refresh=False)` selection + caching; `reset_provider()`.
- `providers/base.py` — `LLMProvider` ABC (`complete`, `extract_json`, `list_models`), `Message`/`to_messages`, `env_model`, `MAX_OUTPUT_TOKENS`, `ProviderError`.
- `providers/_json.py` — `parse_json_object` response coercion.
- `providers/fake.py` — `FakeProvider` (deterministic, no network; used by tests/CI).
- `secretstore/__init__.py` — `resolve_credentials()`, `read_secrets`/`write_secrets`, `encryption_available()`.
- Layer callers: `api/routes.py` (`extract`, `tailor_route`, `cover_letter`, `test_settings`, `list_models`, `_provider_from_update`), `truth/extract.py` (`build_truth_from_text`), `tailor/__init__.py` (`tailor`) and `tailor/{infer,keywords,select}.py`, `coverletter/generate.py` (`build_letter`), `prompts/truth.py` (`extract_system`).

**Provider-service side (concrete adapters that call the external LLM API):**
- `providers/anthropic_provider.py` — `AnthropicProvider.complete/extract_json/list_models` → Anthropic SDK (`messages.create`, `models.list`).
- `providers/openai_provider.py` — `OpenAIProvider._chat/complete/extract_json/list_models` → OpenAI SDK (`chat.completions.create`, `models.list`).
- `providers/ollama_provider.py` — `OllamaProvider._chat/complete/extract_json/list_models` → HTTP `POST /api/chat`, `GET /api/tags` on the Ollama host.

The external LLM services themselves (Anthropic API, OpenAI API, local Ollama daemon) are third-party/out-of-repo; only these adapter classes are the code boundary to them.
