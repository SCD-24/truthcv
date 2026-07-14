<!-- generated:start edge:cover-letter-engine→guardrail-validator -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Cover Letter Engine → Guardrail Validator

- **Participants:** `cover-letter-engine` → `guardrail-validator`
- **Transport:** `in-process`
<!-- generated:end edge:cover-letter-engine→guardrail-validator -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Cover Letter Engine calls the Guardrail Validator through the in-process function `validate(scopes, global_values=())`. There is no serialization or network boundary — both are Python modules in the same process.

**Request** — `coverletter/generate.py:build_letter` constructs the call as:

```python
validate([Scope(texts=claims, allowed=_all_values(truth))])
```

- `Scope.texts` (`list[str]`): the flattened list of `claims` the LLM tagged onto its paragraphs — `[c for para in paragraphs for c in para.get("claims", []) if c]`. Only the tagged claim strings are validated; the connective paragraph prose (`text`) is never sent.
- `Scope.allowed` (`list[str]`): `_all_values(truth)` — **every** non-empty factual value in the truth store (all experiences' role/company/start/end and bullet values, all education degree/school/start/end, all skill values). The cover letter uses a single global scope, so any career fact may be referenced anywhere. `Scope.id` is left as the default `""`.
- The cover-letter path passes **no** `global_values` argument (it relies on the fully-global `allowed` list instead).

**Response** — `guardrail/validate.py:validate` returns a `ValidationResult` dataclass:

- `ok: bool` — `True` when no scope produced any untraceable tokens (`len(blocked) == 0`).
- `unverifiable: list[str]` — deduped, order-preserving list of content tokens in the claims that could not be traced to `allowed`.
- `blocked_claims: list[BlockedClaim]` — one entry per offending text, each with `scope_id`, `text`, and `tokens`.

`build_letter` only reads `check.ok` and `check.unverifiable`; it ignores `blocked_claims`.

**Invariants:**
- The validator is pure and deterministic — no LLM dependency, same input always yields the same result.
- A token is considered verifiable if it is a stopword (see `_STOPWORDS` in `validate.py`), or appears verbatim (after lowercasing/punctuation-stripping via `_tokenize`) in the scope's `allowed` set (plus `global_values`, empty here).
- If `check.ok` is `False`, the engine returns `{"blocked": True, "unverifiable": check.unverifiable, "text": ""}` — the letter body is suppressed entirely (`text == ""`). Nothing is rendered.
- On success it returns `{"blocked": False, "unverifiable": [], "text": <joined paragraphs>}`, where `text` is the paragraph `text` fields joined with `"\n\n"`.

## Auth  (how the interaction is authenticated)

There is no authentication on this interaction. It is a direct in-process function call (`from guardrail import Scope, validate`), not a network/RPC call — there are no tokens, headers, or credentials involved. The Guardrail Validator is deliberately provider-agnostic and pure; it trusts nothing an LLM produced, but the trust boundary it enforces is factual (token traceability against truth), not identity-based.

The surrounding HTTP endpoint `POST /api/cover-letter` (`api/routes.py:cover_letter`) is likewise defined without any auth dependency in `api/routes.py`.

## Flow  (the sequence of the interaction)

1. `api/routes.py:cover_letter` handles `POST /api/cover-letter`. It requires a previously tailored posting (`data_dir()/posting.txt` must exist, else HTTP 400) and calls `coverletter.build_letter(posting, tone, length, load(), get_provider())`.
2. `build_letter` (`coverletter/generate.py`) builds the system/user prompt and calls `provider.extract_json(...)` against `_SCHEMA`, receiving `{"paragraphs": [{"text", "claims"}, ...]}`.
3. It flattens every non-empty `claims` string across all paragraphs into a single `claims` list.
4. It computes `_all_values(truth)` — every factual value across the whole truth store.
5. It calls `validate([Scope(texts=claims, allowed=_all_values(truth))])`.
6. Inside `validate`, for the single scope each claim text is tokenized and each content token checked against the allowed truth tokens (plus stopwords). Any untraceable token is recorded; `ValidationResult.ok` is `False` if any claim was blocked.
7. **If `not check.ok`:** `build_letter` returns `{"blocked": True, "unverifiable": check.unverifiable, "text": ""}`. The route returns `CoverLetterResult(blocked=True, unverifiable=...)` — no HTML/PDF/DOCX is rendered.
8. **If `check.ok`:** `build_letter` joins the paragraph texts and returns `{"blocked": False, ...}`. Only then does the route render the letter (`render_letter_html`), optionally attach/persist it to an application, and produce PDF/DOCX best-effort.

The guardrail always runs before any file is produced — validation is the gate.

## Code  (entry points on both sides, with file paths)

**Cover Letter Engine (caller):**
- `coverletter/generate.py` — `build_letter(posting, tone, length, truth, provider)` is the entry point; it imports `from guardrail import Scope, validate` and invokes `validate(...)`. Helper `_all_values(truth)` builds the `allowed` list.
- `coverletter/__init__.py` — re-exports `build_letter`.
- `api/routes.py` — `cover_letter(body: CoverLetterRequest)` (`POST /api/cover-letter`) is the HTTP entry point that calls `build_letter` (import at `api/routes.py`, in the `cover_letter` handler).

**Guardrail Validator (callee):**
- `guardrail/validate.py` — `validate(scopes, global_values=())` is the entry point. Supporting types: `Scope`, `ValidationResult`, `BlockedClaim`; helpers `_tokenize`, `_truth_tokens`, `_untraceable_tokens`; module-level `_STOPWORDS` and `_TOKEN_RE`.
- `guardrail/__init__.py` — public surface: `from .validate import validate, ValidationResult, Scope, BlockedClaim`.
