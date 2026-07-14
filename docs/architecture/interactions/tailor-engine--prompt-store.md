<!-- generated:start edge:tailor-engine→prompt-store -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Tailor Engine → Prompt Store

- **Participants:** `tailor-engine` → `prompt-store`
- **Transport:** `in-process`
<!-- generated:end edge:tailor-engine→prompt-store -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Tailor Engine (`tailor/`) consumes the Prompt Store (`prompts/`) as an **in-process Python module**, not a network service. There is no serialization, HTTP, or RPC between them; the "contract" is the function signatures re-exported from `prompts/__init__.py`.

**Requests (Tailor → Prompt Store).** The engine calls plain functions and receives strings back:

- `prompts.keywords_system() -> str` — system prompt for keyword extraction. No args.
- `prompts.infer_system() -> str` — system prompt for missing-qualification inference. No args.
- `prompts.infer_truth_block(truth: Truth) -> str` — renders experiences (id + `role — company` + bullets) and a `SKILLS:` line. **Invariant: deliberately omits dates and bullet ids** (inference reasons about content, not identity).
- `prompts.select_system() -> str` — system prompt for selection/rephrasing; concatenates `_CV_STANDARD + CV_STYLE + _CV_ANTI_TELL_RULES`. No args.
- `prompts.select_truth_block(truth: Truth) -> str` — renders experiences **with** ids and date ranges (`[e.id] role — company (start – end)`), and each bullet as `[b.id] value`, plus skills as `[s.id] value`. **Invariant: every fact carries its id** so the selection step can reference facts strictly by id.

**Responses.** Each prompt function returns a `str`. The truth-block builders take a `truth.model.Truth` and return formatted text. The Prompt Store contains **no facts and no schemas** — it emits only prompt text and style fragments.

**Division-of-responsibility invariants (stated in the source):**
- The two truth-block builders render the *same* `Truth` differently on purpose and are explicitly **not merged** (`prompts/tailor.py` docstring).
- JSON I/O schemas (`_SCHEMA` in `tailor/keywords.py`, `tailor/infer.py`, `tailor/select.py`) live **with the feature modules**, not in the Prompt Store (`prompts/__init__.py` docstring). So the Prompt Store owns *what the model is told*; the Tailor Engine owns *the structural I/O contract* and validates the model's reply against its local schema.
- Date ranges are formatted with a spaced en-dash (`start – end`) in `select_truth_block` so they tokenize into separate year tokens for the downstream guardrail.

## Auth  (how the interaction is authenticated)

**None.** This is a same-process import (`import prompts` in `tailor/infer.py`, `tailor/keywords.py`, `tailor/select.py`; direct re-export chain through `prompts/__init__.py`). There is no network boundary, credential, token, or trust check between the Tailor Engine and the Prompt Store — they run in the same Python interpreter within the same service. Authentication is therefore not applicable to this pair; the security-relevant boundary is instead the LLM provider call and the downstream truth-store/guardrail validation, which is out of scope for this interaction.

## Flow  (the sequence of the interaction)

Entry point is `tailor.tailor(posting, truth, provider)` (`tailor/__init__.py`), which drives three sub-steps in order, each pairing a Prompt Store call with a `provider.extract_json(...)` call:

1. **Keyword extraction** — `extract_keywords()` calls `prompts.keywords_system()` for the system prompt and passes the raw posting as the user message to `provider.extract_json`. The Tailor Engine then applies a deterministic junk filter (`_is_junk_token`) and de-dupes.
2. **Selection / rephrasing** — `select_and_rephrase()` builds a user message containing the posting, the extracted keywords, and `prompts.select_truth_block(truth)` (ids + dates), and uses `prompts.select_system()` as the system prompt. The engine validates the reply by id: unknown experience ids are dropped, bullets not belonging to their experience are dropped, and it falls back to verbatim truth if nothing usable comes back.
3. **Inference detection** — `detect_inferences()` pre-filters to uncovered keywords, builds a user message via `_infer_user_message()` which embeds `prompts.infer_truth_block(truth)` (no ids/dates), and uses `prompts.infer_system()` as the system prompt. Replies are filtered against existing facts and each `experienceId` is validated against real ids (unknown → `default_exp`).

The engine assembles the results into a `Draft`, persists it (`save_draft` → `data_dir()/draft.json`), and returns `{keywords, inferences, draft}`. The Prompt Store is stateless across all three steps — every call is a fresh string lookup with no persisted or shared state.

## Code  (entry points on both sides, with file paths)

**Tailor Engine side (callers):**
- `tailor/__init__.py` — `tailor()` orchestrator; imports the sub-modules.
- `tailor/keywords.py` — `extract_keywords()` calls `prompts.keywords_system()`.
- `tailor/select.py` — `select_and_rephrase()` calls `prompts.select_system()` and `prompts.select_truth_block()`.
- `tailor/infer.py` — `detect_inferences()` / `_infer_user_message()` call `prompts.infer_system()` and `prompts.infer_truth_block()`.
- Upstream trigger: `api/routes.py:111` — `tailor_engine.tailor(body.posting, load(), get_provider())` (the API route that invokes the whole flow). Related routes at `api/routes.py:137,143,228` use `valid_experience_ids()`, `claims_for_ids()`, and `load_draft()`.

**Prompt Store side (entry points):**
- `prompts/__init__.py` — public API surface; re-exports the tailor prompt functions and style fragments.
- `prompts/tailor.py` — defines `keywords_system()`, `infer_system()`, `infer_truth_block()`, `select_system()`, `select_truth_block()`, plus the private style constants `_CV_STANDARD` and `_CV_ANTI_TELL_RULES`.
- `prompts/style.py` — defines `CV_STYLE` (injected into `select_system()`); `LETTER_STYLE` is for the cover-letter path and not used by the Tailor Engine.

Note: `prompts/truth.py` and `prompts/coverletter.py` exist in the store but serve other consumers (truth extraction and cover-letter generation), not the Tailor Engine interaction documented here.
