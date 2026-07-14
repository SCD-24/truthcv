<!-- generated:start edge:tailor-engine→llm-provider-layer -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Tailor Engine → LLM Provider Layer

- **Participants:** `tailor-engine` → `llm-provider-layer`
- **Transport:** `in-process`
<!-- generated:end edge:tailor-engine→llm-provider-layer -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Tailor Engine consumes the LLM Provider Layer purely through the `LLMProvider` abstract interface (`providers/base.py`). It never talks to a concrete SDK. Two methods are used:

- **`complete(system: str, messages: list[dict]) -> str`** — plain-text completion. *Not* used by the tailor path (used elsewhere, e.g. cover letters).
- **`extract_json(system: str, messages: list[dict], schema: dict) -> dict`** — the only method the tailor engine calls. Returns a Python `dict` that is meant to conform to the caller-supplied JSON Schema.

**Request shape (tailor → provider).** Each call passes a system prompt string (from `prompts/tailor.py`), a message list of `{"role": "user", "content": ...}` dicts, and a JSON Schema. The tailor engine issues three distinct `extract_json` calls, each with its own schema:

- `extract_keywords` (`tailor/keywords.py`): schema `{keywords: string[]}`; user content is the raw posting.
- `select_and_rephrase` (`tailor/select.py`): schema `{experiences: [{id, bullets: [{id, text}]}], skills: string[]}`; user content is `POSTING / KEYWORDS / truth block`.
- `detect_inferences` (`tailor/infer.py`): schema `{inferences: [{claim, rationale?, experienceId?}]}`; user content lists uncovered keywords plus the truth block.

**Response invariants.** The contract is deliberately *weak on the provider side and enforced on the caller side*:

- `extract_json` guarantees only that it returns a `dict` (parsed best-effort by `providers/_json.py`, which accepts a bare object, a fenced ```json block, or an embedded `{...}` span) or raises `ProviderError` if nothing parseable is found. Schema conformance is *not* validated by the provider — the schema is merely injected into the prompt as an instruction.
- Because of this, the tailor engine treats every field defensively: it checks `isinstance(result, dict)`, defaults missing keys to `[]`, and coerces values with `str(...).strip()`.
- The truthfulness invariant lives entirely in the tailor engine, not the provider (`providers/base.py` explicitly states nothing a provider returns is trusted). In `select_and_rephrase`, an experience `id` unknown to truth is dropped, a bullet `id` not belonging to that experience is dropped, and role/company/dates/education are copied verbatim from truth — only bullet text is taken from the model. In `detect_inferences`, an `experienceId` not in truth is remapped to a default, and claims already in truth or duplicated are skipped. If the model returns nothing usable, `select_and_rephrase` falls back to verbatim truth.

**Output token invariant.** `providers/base.MAX_OUTPUT_TOKENS = 16000` is a shared ceiling so long JSON extractions aren't truncated mid-array (applied by Anthropic and Ollama; OpenAI is left uncapped intentionally).

## Auth  (how the interaction is authenticated)

There is **no auth between the tailor engine and the provider layer** — they are in-process Python calls through the `LLMProvider` interface. Authentication happens one level below, between the provider layer and the external LLM service, and is resolved by the neutral `secretstore` package (not by tailor or api):

- `providers.get_provider()` calls `secretstore.resolve_credentials()`, which merges values from the encrypted `secrets.enc` blob over environment variable defaults (`secretstore/__init__.py`). `secrets.enc` is Fernet-encrypted and only readable when `ENCRYPTION_KEY` is valid; otherwise resolution falls back to env vars.
- The resolved `activeProvider` (env `LLM_PROVIDER`, default `anthropic`) selects the concrete provider; the matching credential is passed to its constructor:
  - `AnthropicProvider`: `anthropicApiKey` / `ANTHROPIC_API_KEY` → `anthropic.Anthropic(api_key=...)`; raises `ProviderError("ANTHROPIC_API_KEY is not set.")` if absent.
  - `OpenAIProvider`: `openaiApiKey` / `OPENAI_API_KEY` → `openai.OpenAI(api_key=...)`; raises `ProviderError("OPENAI_API_KEY is not set.")` if absent.
  - `OllamaProvider`: no API key — uses `ollamaHost` / `OLLAMA_HOST` (default `http://localhost:11434`) over plain HTTP; local/offline.
  - `fake`: `FakeProvider`, no credentials (tests).

The tailor engine receives an already-constructed, already-authenticated `provider` object as a parameter and is unaware of any credentials.

## Flow  (the sequence of the interaction)

1. `api/routes.py:111` handles the tailor request and calls `tailor_engine.tailor(body.posting, load(), get_provider())`. `get_provider()` resolves credentials via `secretstore` and returns a cached, authenticated `LLMProvider` (`providers/__init__.py`).
2. `tailor()` (`tailor/__init__.py`) runs three provider round-trips in sequence, passing the same `provider` instance to each:
   1. `extract_keywords(posting, provider)` → provider `extract_json` with the keywords schema → engine filters out location/arrangement/seniority "junk" tokens deterministically.
   2. `select_and_rephrase(posting, keywords, truth, provider)` → provider `extract_json` with the selection schema → engine validates every returned id against truth, copies headers verbatim, and rephrases only bullets (with verbatim fallback).
   3. `detect_inferences(keywords, truth, provider)` → provider `extract_json` with the inference schema → engine keeps only novel, non-duplicate claims and re-targets invalid experience ids.
3. Inside each provider call: the engine's system prompt is concatenated with a JSON-schema instruction, the request is sent to the LLM service (Anthropic `messages.create`, OpenAI `chat.completions.create` with `response_format=json_object`, or Ollama `POST /api/chat` with `format=json`), and the raw text reply is run through `parse_json_object` to produce a dict (or `ProviderError`).
4. `tailor()` assembles a `Draft`, persists it to `data/draft.json` via `save_draft`, and returns `{keywords, inferences, draft}` to the API route.

## Code  (entry points on both sides, with file paths)

**Tailor Engine (caller) side:**
- `tailor/__init__.py` — `tailor()`, the orchestration entry point that sequences the three provider calls and persists the draft.
- `tailor/keywords.py` — `extract_keywords(posting, provider)`; calls `provider.extract_json(...)`.
- `tailor/select.py` — `select_and_rephrase(posting, keywords, truth, provider)`; calls `provider.extract_json(...)` and enforces the id/verbatim invariants.
- `tailor/infer.py` — `detect_inferences(keywords, truth, provider)`; calls `provider.extract_json(...)`.
- Prompt/schema helpers: `prompts/tailor.py` (`keywords_system`, `select_system`/`select_truth_block`, `infer_system`/`infer_truth_block`).
- Upstream caller: `api/routes.py:111` (`tailor_engine.tailor(..., get_provider())`).

**LLM Provider Layer (callee) side:**
- `providers/base.py` — `LLMProvider` ABC defining `complete`, `extract_json`, `list_models`; `Message`, `ProviderError`, `MAX_OUTPUT_TOKENS`, `env_model`.
- `providers/__init__.py` — `get_provider()` factory (selects provider from resolved credentials; caches).
- `providers/anthropic_provider.py` — `AnthropicProvider.extract_json` / `complete`.
- `providers/openai_provider.py` — `OpenAIProvider.extract_json` / `_chat`.
- `providers/ollama_provider.py` — `OllamaProvider.extract_json` / `_chat` (HTTP to local Ollama).
- `providers/fake.py` — `FakeProvider` (test double; not read in detail here).
- `providers/_json.py` — `parse_json_object`, the shared response coercion used by every `extract_json`.
- Auth source (below the provider layer): `secretstore/__init__.py` — `resolve_credentials()`.
