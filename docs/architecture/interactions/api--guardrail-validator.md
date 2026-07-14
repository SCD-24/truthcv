<!-- generated:start edge:api→guardrail-validator -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: API → Guardrail Validator

- **Participants:** `api` → `guardrail-validator`
- **Transport:** `in-process`
<!-- generated:end edge:api→guardrail-validator -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Guardrail Validator is an **in-process Python library**, not a network service. The API calls it directly via `validate(scopes, global_values)` (`guardrail/validate.py`). All types are plain dataclasses; there is no serialization boundary between the two sides.

**Input** (`api` → `guardrail`):
- `scopes: Iterable[Scope]` — one `Scope` per draft block. `Scope(texts: list[str], allowed: list[str], id: str)`, where `texts` are the rendered draft lines to check and `allowed` are the truth values those lines may draw on. The API builds them in `_render_scopes` (`api/routes.py`): one scope per experience (`id=source_id`, texts = role/company/dates/bullets), one per education entry, one `id="skills"` scope, and one `id="summary"` scope allowed against all experience/education facts.
- `global_values: Iterable[str]` — values allowed in *every* scope. The API passes skill values here.

**Output** (`guardrail` → `api`): `ValidationResult(ok: bool, unverifiable: list[str], blocked_claims: list[BlockedClaim])`, where each `BlockedClaim(scope_id, text, tokens)` names the offending draft line and its untraceable tokens.

**Invariants:**
- **Per-scope traceability:** a content token is verifiable only if it is a stopword, appears in that scope's own `allowed`, or is in `global_values`. A token that exists only in a *different* scope is unverifiable — this is what stops a fact from one job attaching to another.
- **Determinism / purity:** no LLM, no I/O; same input always yields the same result.
- `ok` is `True` iff `blocked_claims` is empty.
- Identity fields (name/contact/links) are guardrail-exempt and are never placed in a scope; the API strips HTML before diffing (`_strip_html`) so markup is not treated as claims.
- At the API wire edge, `BlockedClaim` is mapped to `BlockedClaimModel` (camelCase: `claimId`, `experienceId`, `text`, `tokens`) with a stable `claimId = sha256(scope_id\ntext)[:16]` (`api/schemas.py`, `_claim_id`).

## Auth  (how the interaction is authenticated)

**None.** This is a same-process function call within the Python backend, so there is no authentication, token, or transport-layer security involved. The guardrail is provider-agnostic and trusts nothing an LLM produced; its only "gate" is the deterministic token diff, not any credential check. (Provider credentials and the encryption key handled elsewhere in `api/secrets.py` do not participate in this interaction.)

## Flow  (the sequence of the interaction)

For `POST /api/render` (`render_route` in `api/routes.py`), which is the hard-rule path:

1. Load the tailored draft (`tailor_engine.load_draft()`); 400 if none exists.
2. Load the truth store (`truth.load()`) and collect `skill_values`.
3. Read optional per-claim decisions from `body.approvals` (`approved_claim_ids`, `denied_claim_ids`).
4. Build scopes with `_render_scopes(draft, truth)` — one per draft block, keyed by its truth `source_id`.
5. Apply render-scoped approvals with `_apply_approvals`: *denied* claims are removed from `scope.texts`; *approved* claims have their text appended to `scope.allowed` (traceable for this render only — **never** written to truth).
6. **Call the guardrail first:** `result = validate(scopes, global_values=skill_values)`.
7. If `result.ok` is `False`: return immediately with `RenderResult(blocked=True, unverifiable=..., blocked_claims=[...])` — **nothing is rendered**.
8. If ok: drop denied claims from the draft (`_filter_denied_draft`), render HTML/PDF/DOCX, run ATS lint, optionally attach to an application, and return `RenderResult(blocked=False, ...)`.

A parallel path exists in cover-letter generation (`coverletter/generate.py`, invoked by `POST /api/cover-letter`): the LLM's claimed facts are collected and passed as a single `Scope` allowed against *all* truth values; if `validate(...).ok` is false the letter is blocked with no text.

Note: the manual-edit save routes (`PUT /api/applications/{id}/cv` and `.../cover-letter`) intentionally **do not** call the guardrail — hand edits are trusted and saved as-is.

## Code  (entry points on both sides, with file paths)

**Guardrail Validator (callee):**
- `guardrail/validate.py` — `validate(scopes, global_values)` is the public entry point; supporting types `Scope`, `ValidationResult`, `BlockedClaim`, and internal helpers `_tokenize`, `_truth_tokens`, `_untraceable_tokens`, plus the `_STOPWORDS` set.
- `guardrail/__init__.py` — re-exports `validate`, `ValidationResult`, `Scope`, `BlockedClaim`.

**API (caller):**
- `api/routes.py`:
  - import: `from guardrail import Scope, validate` (line 13).
  - `render_route` (`@router.post("/render")`) — primary caller; invokes `validate(scopes, global_values=skill_values)` (line 245).
  - `_render_scopes(draft, truth)` — constructs the `Scope` list.
  - `_apply_approvals(scopes, approved, denied)` — adjusts `allowed`/`texts` before validation.
  - `_claim_id(scope_id, text)` — stable id bridging `BlockedClaim` ↔ `BlockedClaimModel`.
  - `_strip_html(text)` — pre-processes edited HTML so the guardrail sees prose.
- `api/schemas.py` — wire models `BlockedClaimModel`, `RenderApprovals`, `RenderRequest`, `RenderResult`, `SaveDocumentResult`.
- Secondary caller: `coverletter/generate.py` — `from guardrail import Scope, validate` (line 13), `validate([Scope(texts=claims, allowed=_all_values(truth))])` in `build_letter` (line 68), reached from `cover_letter` in `api/routes.py`.
