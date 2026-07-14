<!-- generated:start edge:cover-letter-engine→llm-provider-layer -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Cover Letter Engine → LLM Provider Layer

- **Participants:** `cover-letter-engine` → `llm-provider-layer`
- **Transport:** `in-process`
<!-- generated:end edge:cover-letter-engine→llm-provider-layer -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Cover Letter Engine calls the LLM Provider Layer through the abstract `LLMProvider` interface (`providers/base.py`), using a **single method**: `extract_json(system, messages, schema)`.

**Request** (built in `coverletter/generate.py::build_letter`):
- `system` (str): the prompt from `prompts.cover_letter_system(tone, length)`, which describes the writing standard, tone/voice, anti-"AI-tell" style rules, and the guardrail contract instructing the model to tag every factual sentence with its verbatim claims.
- `messages` (`list[dict[str,str]]`): a single `{"role": "user", "content": ...}` message containing `POSTING:\n{posting}` plus `CANDIDATE FACTS:\n{prompts.cover_letter_facts_block(truth)}` (the full career rendered as plain text).
- `schema` (dict, JSON Schema `_SCHEMA` in `generate.py`): requires
  ```json
  {"paragraphs": [{"text": "string", "claims": ["string", ...]}]}
  ```
  where `text` is required per paragraph and `claims` is optional.

**Response**: `extract_json` returns a parsed JSON object (`dict`). The engine reads `result["paragraphs"]`; each paragraph contributes `text` (prose) and `claims` (facts asserted). The provider layer guarantees only that a *parseable JSON object* is returned (`providers/_json.py::parse_json_object` accepts bare JSON, fenced ```json blocks, or an embedded balanced `{...}`); it does **not** validate the object against `_SCHEMA` or against the truth store.

**Invariants**:
- The provider is untrusted: nothing it returns is used until the guardrail validates it. `build_letter` collects all `claims` across paragraphs and calls `validate([Scope(texts=claims, allowed=_all_values(truth))])`. If any claim is unverifiable, the letter is blocked (`{"blocked": True, "unverifiable": [...], "text": ""}`) and no text is returned.
- The engine defensively handles malformed output: if `result` is not a dict, `paragraphs` defaults to `[]`; missing `claims`/`text` keys are treated as empty.
- The provider layer imposes no cover-letter-specific logic; it is provider-agnostic (`base.py` docstring). `MAX_OUTPUT_TOKENS = 16000` caps output on Anthropic/Ollama; OpenAI is intentionally uncapped.
- The final `text` is paragraphs' `text` joined with blank lines; connective narrative (no claims) is never guardrail-checked.

## Auth  (how the interaction is authenticated)

The Cover Letter Engine itself performs **no authentication**. It receives an already-constructed `LLMProvider` instance as a function argument (`build_letter(..., provider)`) and simply calls it. Authentication is entirely the responsibility of the provider layer and how it is instantiated.

- The provider is created by `providers.get_provider()` (`providers/__init__.py`), which calls `secretstore.resolve_credentials()` (`secretstore/__init__.py`).
- `resolve_credentials()` merges values from the encrypted `secrets.enc` blob (decrypted with a Fernet `ENCRYPTION_KEY`) over environment variables, in the order **secrets.enc → env → default**. It returns `activeProvider`, `anthropicApiKey`, `openaiApiKey`, `ollamaHost`, and `model`.
- Based on `activeProvider` (env `LLM_PROVIDER`, default `anthropic`), `get_provider` constructs the concrete provider with the matching credential:
  - `AnthropicProvider` — requires an API key (arg → `ANTHROPIC_API_KEY`); raises `ProviderError("ANTHROPIC_API_KEY is not set.")` if missing. The key authenticates the `anthropic.Anthropic(api_key=...)` client.
  - `OpenAIProvider` — requires an API key (arg → `OPENAI_API_KEY`); passes it to `openai.OpenAI(api_key=...)`.
  - `OllamaProvider` — uses a `host` (no API key; local network endpoint).
  - `fake` — no credentials (test use).
- In the request path (`api/routes.py::cover_letter`), `get_provider()` supplies the provider to `build_letter`. Provider misconfiguration surfaces as `ProviderError`, which the route maps to HTTP `502`.

There is no per-call token/signature between the engine and the provider; the outbound API key is the only credential, and it lives with the concrete provider client.

## Flow  (the sequence of the interaction)

1. `POST /api/cover-letter` (`api/routes.py::cover_letter`) verifies a tailored `posting.txt` exists, then calls `build_letter(posting, body.tone, body.length, load(), get_provider())`.
2. `get_provider()` resolves credentials via `secretstore.resolve_credentials()` and returns (or reuses a cached) concrete `LLMProvider`.
3. `build_letter` (`coverletter/generate.py`) builds the `system` prompt (`prompts.cover_letter_system`) and the `user` message (posting + `cover_letter_facts_block`).
4. `build_letter` calls `provider.extract_json(system, [user_msg], _SCHEMA)`.
5. The concrete provider (e.g. `AnthropicProvider.extract_json`) appends the JSON-schema instruction to the system prompt, calls the LLM (`complete` → SDK API call), and passes the raw text through `parse_json_object` to produce a `dict`.
6. `build_letter` extracts `paragraphs`, flattens all `claims`, and runs the **guardrail**: `validate([Scope(texts=claims, allowed=_all_values(truth))])`.
7. If any claim is unverifiable → returns `{"blocked": True, "unverifiable": [...], "text": ""}`; the route returns `CoverLetterResult(blocked=True, unverifiable=...)` and nothing is rendered.
8. If all claims pass → returns `{"blocked": False, "unverifiable": [], "text": <joined paragraphs>}`; the route renders/saves the letter and returns URLs and text.
9. Any `ProviderError` (or other exception) raised by the provider layer during step 4/5 propagates out of `build_letter` and is caught in the route, mapped to HTTP `502`.

## Code  (entry points on both sides, with file paths)

**Cover Letter Engine side (caller):**
- `coverletter/generate.py` — `build_letter(posting, tone, length, truth, provider)`: the sole entry point; constructs prompts/messages and calls `provider.extract_json(...)`. Defines `_SCHEMA` and `_all_values`.
- `coverletter/__init__.py` — exports `build_letter`.
- `prompts/coverletter.py` — `cover_letter_system(tone, length)` and `cover_letter_facts_block(truth)`: build the request's system prompt and facts payload.
- `api/routes.py` — `cover_letter(body: CoverLetterRequest)` (`POST /api/cover-letter`): obtains the provider via `get_provider()` and invokes `build_letter`.

**LLM Provider Layer side (callee):**
- `providers/base.py` — `LLMProvider` ABC defining `extract_json(system, messages, schema)` (the method the engine calls), plus `complete`, `list_models`, `MAX_OUTPUT_TOKENS`, `ProviderError`.
- `providers/__init__.py` — `get_provider(refresh=False)`: selects/instantiates the concrete provider from resolved credentials; `reset_provider()`.
- `providers/anthropic_provider.py` — `AnthropicProvider.extract_json` / `.complete` (default provider).
- `providers/openai_provider.py` — `OpenAIProvider.extract_json` / `.complete`.
- `providers/ollama_provider.py` — Ollama implementation (not read in detail, but selected by `get_provider`).
- `providers/fake.py` — `FakeProvider` (test provider).
- `providers/_json.py` — `parse_json_object(text)`: coerces raw model output into the `dict` returned by `extract_json`.
- `secretstore/__init__.py` — `resolve_credentials()`: supplies the provider name, model, and API keys used to build the provider (auth source).
