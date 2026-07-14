<!-- generated:start edge:truth-store→llm-provider-layer -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Truth Store → LLM Provider Layer

- **Participants:** `truth-store` → `llm-provider-layer`
- **Transport:** `in-process`
<!-- generated:end edge:truth-store→llm-provider-layer -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Truth Store consumes the LLM Provider Layer through one interface method, `LLMProvider.extract_json` (`providers/base.py`). The call site is `truth/extract.py:build_truth_from_text`:

```python
result = provider.extract_json(
    prompts.extract_system(),                     # system prompt (str)
    [{"role": "user", "content": text}],          # messages: raw profile text
    _EXTRACTION_SCHEMA,                            # JSON Schema (dict)
)
```

**Request shape** (`extract_json(system, messages, schema)`):
- `system: str` — the extraction system prompt from `prompts.extract_system()`.
- `messages: list[dict[str, str]]` — chat messages, each `{"role": "system"|"user"|"assistant", "content": str}`. The Truth Store sends a single user message carrying the full profile text.
- `schema: dict[str, Any]` — a JSON Schema. `_EXTRACTION_SCHEMA` (in `truth/extract.py`) requires top-level `experiences`, `education`, `skills`, and an optional `profile` object (name/email/phone/location/links/summary). Each experience carries `role`, `company`, `start`, `end`, and a `bullets` string array.

**Response shape**: a single JSON object (`dict[str, Any]`) that the provider coerces to conform to `schema`. Concrete providers append a "respond with a single JSON object conforming to this schema, JSON only" instruction to the system prompt, call the model, and run the text through `parse_json_object` (`providers/_json.py`), which accepts a bare object, a fenced ```json block, or an object embedded in prose. If nothing parseable is found it raises `ProviderError` (`providers/base.py`).

**Invariants**:
- The provider only *proposes* structure; it is not trusted. `build_truth_from_text` treats a non-`dict` result as `{}` (defensive), then re-derives every field itself: it strips/normalizes values, drops empty rows, mints stable unique ids via `make_id`, and tags every extracted fact `source="linkedin-pdf"`. The provider's output never becomes truth directly.
- After building, the store runs `store.save(truth)` which calls `validate` (unique ids across experiences/bullets/education/skills; `source` ∈ `SOURCE_VALUES`), then atomically writes `truth.yaml`.
- Provider output tokens are capped generously (`MAX_OUTPUT_TOKENS = 16000`) to avoid mid-array JSON truncation on long profiles.
- The interface contract is provider-agnostic: `providers/base.py` states "no truthfulness logic may depend on the concrete provider."

## Auth  (how the interaction is authenticated)

This is an **in-process Python call** — there is no wire protocol or auth between `truth` and `providers`. Authentication happens one level below, when the concrete provider talks to the external LLM API.

- The Truth Store never resolves credentials itself. The caller (`api/routes.py:/extract`) passes an already-constructed provider via `get_provider()`.
- `providers.get_provider()` (`providers/__init__.py`) selects the implementation from `secretstore.resolve_credentials()`, keyed by `activeProvider` (`LLM_PROVIDER`, default `anthropic`).
- `secretstore.resolve_credentials()` (`secretstore/__init__.py`) merges values from the encrypted `secrets.enc` blob (decrypted with `ENCRYPTION_KEY` via Fernet) over environment-variable defaults; `secrets.enc` wins where present, else the env var.
- The credential is then handed to the concrete provider constructor. For example `AnthropicProvider` (`providers/anthropic_provider.py`) uses `api_key or os.environ["ANTHROPIC_API_KEY"]` and raises `ProviderError("ANTHROPIC_API_KEY is not set.")` if absent, then builds `anthropic.Anthropic(api_key=key)`. OpenAI/Ollama providers resolve their own key/host analogously.

So the Truth Store's dependency on auth is indirect: it receives a fully-authenticated provider object and simply invokes `extract_json` on it.

## Flow  (the sequence of the interaction)

1. A prior `/upload` extracts PDF text and persists it plus a source hash (`api/routes.py:upload` → `persist_source_text`, `persist_source_hash`).
2. `POST /api/extract` (`api/routes.py:extract`) loads the source text, then calls `build_truth_from_text(text, get_provider())`.
3. **Cache short-circuit** (`truth/extract.py:_cached_for`): the store loads persisted truth and compares `store.loaded_source_hash()` against `store.source_hash(text)` (whitespace-normalized SHA-256). If they match and the truth is non-empty, it returns the cached Truth **without calling the provider** — a repeat of the same source costs no tokens.
4. On a cache miss, the Truth Store calls `provider.extract_json(extract_system(), [{"role":"user","content":text}], _EXTRACTION_SCHEMA)`.
5. The concrete provider appends the schema instruction to the system prompt, calls the LLM API (e.g. `AnthropicProvider.complete` → `client.messages.create`), collects the text, and returns a parsed JSON object via `parse_json_object` (or raises `ProviderError`).
6. Back in the store, `build_truth_from_text` normalizes the result, mints stable unique ids, and tags all facts `source="linkedin-pdf"`, assembling a `Truth`.
7. The store persists: `store.save(truth)` (validate + atomic write of `truth.yaml`) and `store.persist_source_hash(text)` (records the source fingerprint so step 3 can skip next time).
8. The route wraps the returned `Truth` as a `TruthDoc` response. Provider failures surface as HTTP 502 (`ProviderError` or any upstream SDK error is caught in `api/routes.py:extract`).

## Code  (entry points on both sides, with file paths)

**Truth Store side (caller):**
- `truth/extract.py` — `build_truth_from_text(text, provider)` is the entry point that invokes the provider (call at `truth/extract.py:120`); `_cached_for` implements the token-saving skip; `write_confirmed` appends user-confirmed bullets (no provider call).
- `truth/store.py` — `load`, `save`, `validate`, `source_hash`, `persist_source_hash`, `loaded_source_hash` (persistence + the source-hash cache used to decide whether to call the provider).
- `truth/model.py` — `Truth`, `Experience`, `Bullet`, `Education`, `Skill`, `Profile`, `make_id`, `SOURCE_VALUES` (the shapes the provider output is coerced into).
- Upstream trigger: `api/routes.py` — `extract()` route (`from truth.extract import build_truth_from_text`, call at `api/routes.py:83`).

**LLM Provider Layer side (callee):**
- `providers/base.py` — `LLMProvider` ABC defining `extract_json(system, messages, schema)` (and `complete`, `list_models`); `MAX_OUTPUT_TOKENS`; `ProviderError`.
- `providers/__init__.py` — `get_provider(refresh=False)` factory selecting the implementation from resolved credentials.
- `providers/_json.py` — `parse_json_object(text)` shared response coercion used by every `extract_json`.
- Concrete implementations: `providers/anthropic_provider.py`, `providers/openai_provider.py`, `providers/ollama_provider.py` (each defines `extract_json`), and `providers/fake.py` (test double).
- Credential source (auth boundary): `secretstore/__init__.py` — `resolve_credentials()`, `read_secrets()`, `encryption_available()`.
