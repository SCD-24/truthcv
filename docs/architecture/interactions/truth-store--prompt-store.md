<!-- generated:start edge:truth-store→prompt-store -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Truth Store → Prompt Store

- **Participants:** `truth-store` → `prompt-store`
- **Transport:** `in-process`
<!-- generated:end edge:truth-store→prompt-store -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The interaction is an **in-process Python function call**, not a network API. The Truth Store consumes exactly one thing from the Prompt Store: the extraction *system prompt*.

- **Request (Truth Store → Prompt Store):** a zero-argument call `prompts.extract_system()`. No inputs are passed; the prompt is a static, self-contained instruction.
- **Response (Prompt Store → Truth Store):** a single `str` — the system prompt instructing the LLM to extract verifiable facts from LinkedIn profile text, grouped by experience, copied verbatim with no inference (`prompts/truth.py::extract_system`).

The returned string is then used by the Truth Store as the `system` argument to `provider.extract_json(system, messages, schema)` (`truth/extract.py:120`). Note the division of responsibility:

- The **prompt text** (what the model is told) lives in the Prompt Store.
- The **JSON output schema** (`_EXTRACTION_SCHEMA`, an object with required `experiences`/`education`/`skills` plus optional `profile`) stays in the Truth Store (`truth/extract.py`), not the Prompt Store. `prompts/__init__.py` documents this intentional split: prompt text in the store, structural I/O contracts with their feature module.

**Invariants:**
- The prompt only asks the model to *group and copy verbatim* — never infer or add. Nothing it returns is trusted at this stage.
- Every extracted fact is tagged `source="linkedin-pdf"` by the Truth Store after the call (`truth/extract.py`), regardless of prompt content. Valid sources are `("linkedin-pdf", "user-confirmed")` (`truth/model.py`).
- The model's output is treated as untrusted structure: ids are re-generated deterministically, duplicates dropped, and the result is validated (`store.validate`) before persistence. Trust is only established later by the deterministic guardrail at render time.

## Auth  (how the interaction is authenticated)

There is **no authentication** on this interaction. The Prompt Store (`prompts` package) and Truth Store (`truth` package) are modules in the same Python process; the Truth Store obtains the prompt by a direct `import prompts` and function call (`truth/extract.py:16`, `:120`). No tokens, credentials, network boundary, or trust check exist between the two — they are trusted code within one deployment. (Authentication/secrets only appear at the outer edge, e.g. the `secretstore` and provider API keys, which are outside this interaction.)

## Flow  (the sequence of the interaction)

1. An HTTP route (`api/routes.py:83`) calls `build_truth_from_text(text, get_provider())` with the raw profile text extracted from an uploaded PDF.
2. The Truth Store checks its cache: it loads any persisted truth (`store.load`) and compares `store.loaded_source_hash()` against `store.source_hash(text)` (whitespace-normalized SHA-256). On a match it returns the cached `Truth` immediately and **the Prompt Store is never touched** (no LLM pass, no tokens) (`truth/extract.py::_cached_for`, `build_truth_from_text`).
3. On a cache miss, the Truth Store calls `prompts.extract_system()` to fetch the system prompt string from the Prompt Store (`truth/extract.py:121`).
4. The Truth Store calls `provider.extract_json(system_prompt, [{"role": "user", "content": text}], _EXTRACTION_SCHEMA)`, sending the Prompt Store's system prompt plus the profile text and its own schema to the LLM provider (`truth/extract.py:120`, `providers/base.py`).
5. The Truth Store normalizes the returned JSON: builds `Experience`/`Bullet`/`Education`/`Skill`/`Profile` objects, assigns collision-free ids via `make_id`, dedups bullets/skills, and tags each with `source="linkedin-pdf"`.
6. The Truth Store validates and atomically persists the result to `truth.yaml` (`store.save`) and records the source hash to `truth.meta.yaml` (`store.persist_source_hash`) so a repeat of the same source skips step 3–4 next time.
7. The structured `Truth` is returned to the caller.

## Code  (entry points on both sides, with file paths)

**Prompt Store side (producer of the prompt):**
- `prompts/truth.py` → `extract_system()` — the extraction system prompt, the only prompt consumed in this interaction.
- `prompts/__init__.py` → re-exports `extract_system` as the package's public API (callers use `prompts.extract_system()`, never the raw constant).

**Truth Store side (consumer):**
- `truth/extract.py` → `build_truth_from_text(text, provider)` — the entry point that imports `prompts` (line 16), calls `prompts.extract_system()` (line 121), and drives the provider call (line 120). Also `write_confirmed(...)` for user-confirmed additions (does not use the Prompt Store).
- `truth/store.py` → `load` / `save` / `validate` / `source_hash` / `persist_source_hash` / `loaded_source_hash` — persistence and the caching that can short-circuit the Prompt Store call.
- `truth/model.py` → `Truth` and related dataclasses plus `make_id`; `_EXTRACTION_SCHEMA` (the JSON contract) lives in `truth/extract.py`.

**Upstream caller / boundary between them:**
- `api/routes.py:18,83` → imports and invokes `build_truth_from_text`, wiring in the active provider via `get_provider()`.
- `providers/base.py` → `LLMProvider.extract_json(system, messages, schema)`, the interface through which the Prompt Store's prompt string reaches the model.
