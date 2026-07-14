<!-- generated:start edge:guardrail-validator→truth-store -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Guardrail Validator → Truth Store

- **Participants:** `guardrail-validator` → `truth-store`
- **Transport:** `in-process`
<!-- generated:end edge:guardrail-validator→truth-store -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The interaction is **in-process Python**, not a network call. The Guardrail Validator (`guardrail/`) consumes structured facts read from the Truth Store (`truth/`); there is no HTTP contract between them.

**Truth Store output** — `truth.load()` (`truth/store.py`) reads `data/truth.yaml` and returns a `Truth` (`truth/model.py`): a record of `experiences` (each with `role`, `company`, `start`, `end`, `source`, and a list of `bullets`), `education` (`degree`/`school`/dates), flat `skills`, and a `profile` (identity + free-text `summary`). Loading enforces invariants via `truth.store.validate()`: every id is non-empty and unique across all objects, and every `source` is in `SOURCE_VALUES = ("linkedin-pdf", "user-confirmed")`; violations raise `ValueError`. `load()` also fails safe on the legacy flat shape, returning `Truth.empty()`.

**Guardrail input** — `guardrail.validate(scopes, global_values=())` (`guardrail/validate.py`) takes an iterable of `Scope(id, texts, allowed)` plus `global_values`. Each scope pairs draft `texts` (bullets/lines to check) with the `allowed` truth values they may draw on. The caller (`api/routes.py::_render_scopes`) builds one scope per truth object: draft experience texts are scoped to that experience's own `[role, company, start, end, *bullet values]`, education likewise, `skills` is a scope, and the profile `summary` gets a scope allowed against all experience/education facts. Skills are passed as `global_values` (allowed in every scope).

**Guardrail output** — a `ValidationResult` with `ok: bool`, `unverifiable: list[str]` (deduped untraceable tokens), and `blocked_claims: list[BlockedClaim]` (each a `scope_id` + `text` + offending `tokens`). `to_dict()` serializes to `{ok, unverifiable, blockedClaims}`.

**Core invariant**: a draft content token is verifiable only if it is a stopword/pure formatting, appears in `global_values`, or appears verbatim (post-tokenization) in *its own scope's* `allowed` set. A token that exists only in a *different* scope is unverifiable — this is the per-experience rule that stops a fact from one job attaching to another. Validation is deterministic (no LLM); identical input always yields identical output. The guardrail never mutates the Truth Store.

## Auth  (how the interaction is authenticated)

There is **no authentication** on this interaction, and none is expected: both modules run in the same Python process within a single-user application. The Guardrail Validator receives plain in-memory `Scope` objects; the Truth Store reads/writes a local file (`data/truth.yaml`, path from `DATA_DIR`, default `./data`) on a mounted volume with no credentials. Trust is enforced structurally, not by identity: `guardrail/__init__.py` states it "never trusts anything an LLM produced" and diffs draft tokens against truth values, while `truth/__init__.py` declares itself "the single origin of all facts." The only integrity control is the Truth Store's `validate()` (unique ids, allowed `source` values) and atomic `save()` (write-to-temp then `replace`).

## Flow  (the sequence of the interaction)

The API layer (`api/routes.py`) orchestrates both sides. Two flows exercise the interaction:

**Render flow (`POST /api/render`, `render_route`):**
1. Load the tailored draft (`tailor_engine.load_draft()`); 400 if absent.
2. Load facts from the Truth Store: `truth = load()`; collect `skill_values`.
3. Build guardrail scopes with `_render_scopes(draft, truth)` — one `Scope` per truth object, each draft block scoped to its source experience/education facts; a `summary` scope; a `skills` scope.
4. Apply per-render approvals/denials with `_apply_approvals` (approve appends the claim's text to that scope's `allowed` for this render only — no truth write; deny drops it from `texts`).
5. **Guardrail runs FIRST**: `result = validate(scopes, global_values=skill_values)`.
6. If `not result.ok`: return `RenderResult(blocked=True, ...)` carrying `unverifiable` tokens and `blocked_claims` (each with a stable `claim_id`). **Nothing is rendered.**
7. If `ok`: drop denied claims and render HTML/PDF/DOCX.

**Cover-letter flow (`POST /api/cover-letter` → `coverletter/generate.py::build_letter`):**
1. Route loads `truth = load()` and calls `build_letter(..., truth, provider)`.
2. The LLM returns paragraphs tagging factual `claims`.
3. Claims are validated in a single global scope: `validate([Scope(texts=claims, allowed=_all_values(truth))])` — the letter may reference any fact across the whole career.
4. If not ok, the letter is blocked (`text=""`); otherwise the prose is returned.

## Code  (entry points on both sides, with file paths)

**Guardrail Validator (`guardrail-validator`):**
- `guardrail/__init__.py` — package entry, re-exports `validate`, `ValidationResult`, `Scope`, `BlockedClaim`.
- `guardrail/validate.py` — `validate(scopes, global_values=())` is the entry point; supporting `_tokenize`, `_truth_tokens`, `_untraceable_tokens`, and the `Scope` / `ValidationResult` / `BlockedClaim` dataclasses.

**Truth Store (`truth-store`):**
- `truth/__init__.py` — package entry, re-exports `load`, `save`, `validate`, `Truth`, model classes.
- `truth/store.py` — `load()` (read `truth.yaml` → `Truth`), `save()`, `validate(truth)` (id/source invariants), `data_dir()`/`truth_path()`.
- `truth/model.py` — the `Truth`/`Experience`/`Education`/`Skill`/`Profile` dataclasses and `SOURCE_VALUES`.

**Orchestration boundary (where the two meet):**
- `api/routes.py` — `_render_scopes(draft, truth)` maps loaded truth into guardrail `Scope`s; `render_route` (`POST /api/render`) calls `load()` then `validate(...)`; `_apply_approvals` / `_filter_denied_draft` handle per-render approvals.
- `coverletter/generate.py` — `build_letter(...)` calls `load()`-supplied `truth` into `validate([Scope(...)])` via `_all_values(truth)`.
