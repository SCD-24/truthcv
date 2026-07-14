<!-- generated:start edge:cover-letter-engine→prompt-store -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Cover Letter Engine → Prompt Store

- **Participants:** `cover-letter-engine` → `prompt-store`
- **Transport:** `in-process`
<!-- generated:end edge:cover-letter-engine→prompt-store -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Cover Letter Engine (`coverletter/`) consumes the Prompt Store (`prompts/`) as an in-process Python API. There is no network protocol; the "contract" is the function signatures re-exported from `prompts/__init__.py` and the invariants their prompt text encodes.

Two functions are used:

- **`cover_letter_system(tone: str, length: str) -> str`** — Returns the system prompt. `tone` is matched case-insensitively against `{"professional", "warm", "concise"}`, defaulting to `"professional"` for any unknown value. `length` is lower-cased and interpolated into the prompt as a length hint. The returned string composes: base instruction, `_WRITING_STANDARD`, the tone `direction`, `LETTER_STYLE`, `_ANTI_TELL_RULES`, and a **guardrail contract clause**. That clause is the key invariant: every sentence stating a candidate fact must list that fact *verbatim* in its `claims`, and no fact may be invented.

- **`cover_letter_facts_block(truth: Truth) -> str`** — Renders the candidate's whole career (all `truth.experiences` with their bullets, all `truth.education`, and joined `truth.skills`) as a plain-text `CANDIDATE FACTS` block. Unlike the CV path, this renders the *entire* history, not id-referenced selections.

Invariants that couple the two sides:
- The Prompt Store owns only prompt *text*. The JSON I/O schema (`_SCHEMA` with `paragraphs[].text` and `paragraphs[].claims`) lives on the engine side (`coverletter/generate.py`), not in the store.
- Style/writing fragments (`LETTER_STYLE`, `_WRITING_STANDARD`, `_ANTI_TELL_RULES`) add **no facts** and must not override the guardrail contract; this is asserted in the docstrings of `prompts/style.py` and `prompts/coverletter.py`.
- The engine trusts nothing the model returns: the `claims` tagged per the system-prompt contract are re-validated deterministically against the truth store before any text is released.

## Auth  (how the interaction is authenticated)

None. This is an in-process function call between two Python packages in the same application; the engine simply `import prompts` and calls the re-exported functions. There is no token, header, credential, or network boundary between `coverletter` and `prompts`. (Secrets/auth in this repo, e.g. `secretstore/`, concern LLM provider access, not this module-to-module interaction.)

## Flow  (the sequence of the interaction)

1. A caller invokes `build_letter(posting, tone, length, truth, provider)` in `coverletter/generate.py`.
2. The engine calls `prompts.cover_letter_facts_block(truth)` to render the candidate's full career as plain text, and embeds it in a user message alongside the posting: `POSTING:\n...\n\nCANDIDATE FACTS:\n...`.
3. The engine calls `prompts.cover_letter_system(tone, length)` to obtain the system prompt (which carries the claim-tagging guardrail contract).
4. The engine passes the system prompt, the user message, and the locally-owned `_SCHEMA` to `provider.extract_json(...)`, receiving `{"paragraphs": [{"text", "claims"}, ...]}`.
5. The engine flattens all per-paragraph `claims` and calls `guardrail.validate([Scope(texts=claims, allowed=_all_values(truth))])`.
6. If validation fails (`not check.ok`), it returns `{"blocked": True, "unverifiable": check.unverifiable, "text": ""}` — no letter text is emitted.
7. If validation passes, it joins the non-empty paragraph `text` values with blank lines and returns `{"blocked": False, "unverifiable": [], "text": <letter>}`.

The Prompt Store is passive: it only produces strings in steps 2–3 and has no callbacks into the engine.

## Code  (entry points on both sides, with file paths)

**Cover Letter Engine (consumer):**
- `coverletter/generate.py` — `build_letter(...)` is the entry point; it calls `prompts.cover_letter_facts_block(truth)` and `prompts.cover_letter_system(tone, length)`, defines the response `_SCHEMA`, and runs guardrail validation via `_all_values(truth)`.
- `coverletter/__init__.py` — package marker for the engine.

**Prompt Store (provider):**
- `prompts/__init__.py` — the store's public API; re-exports `cover_letter_system` and `cover_letter_facts_block` (among other prompts).
- `prompts/coverletter.py` — implements `cover_letter_system(tone, length)` and `cover_letter_facts_block(truth)`, plus the private fragments `_TONE_DIRECTION`, `_WRITING_STANDARD`, and `_ANTI_TELL_RULES`.
- `prompts/style.py` — provides `LETTER_STYLE`, injected into the system prompt by `cover_letter_system`.

Both sides depend on the shared `Truth` model from `truth/model.py`, which defines the `experiences`, `education`, and `skills` fields these functions read.
