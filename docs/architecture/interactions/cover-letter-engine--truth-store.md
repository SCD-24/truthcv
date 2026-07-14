<!-- generated:start edge:cover-letter-engine→truth-store -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Cover Letter Engine → Truth Store

- **Participants:** `cover-letter-engine` → `truth-store`
- **Transport:** `in-process`
<!-- generated:end edge:cover-letter-engine→truth-store -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Cover Letter Engine consumes the Truth Store through a single in-process object: a `truth.model.Truth` dataclass returned by `truth.load()`. There is no serialized request/response between them — they are Python modules in the same process. `Truth` carries:

- `experiences: list[Experience]` — each has `role, company, start, end, source` plus `bullets: list[Bullet]` (each bullet has `id, value, source`).
- `education: list[Education]` — `degree, school, start, end, source`.
- `skills: list[Skill]` — flat `id, value, source`.
- `profile: Profile` — identity + `summary` (not used by the cover-letter path).

The engine reads `Truth` two ways:
- **As facts for the prompt:** `prompts.cover_letter_facts_block(truth)` flattens the whole career (experiences with bullets, education, skills) into plain text under `CANDIDATE FACTS:`.
- **As the allowed-value set for validation:** `_all_values(truth)` collects every non-empty factual string — `role, company, start, end`, each bullet `value`, education fields, and skill `value`s.

`build_letter(posting, tone, length, truth, provider)` returns `{"blocked": bool, "unverifiable": list[str], "text": str}`.

**Invariants:**
- The Truth Store is the sole origin of facts; the engine never asserts a fact absent from `truth` (`truth/__init__.py` docstring).
- Validation is *global* for cover letters: unlike the CV render path (per-experience scopes), every LLM-tagged `claim` is checked against one flat `allowed` set of all truth values via a single `Scope(texts=claims, allowed=_all_values(truth))`.
- If any tagged claim is not verifiable, the whole letter is blocked and `text` is `""` — nothing partial is returned.
- Connective/interpretive prose carries no claims and is not validated (only the `claims` array per paragraph is).

## Auth  (how the interaction is authenticated)

None. The Cover Letter Engine and Truth Store are modules inside the same FastAPI process (`coverletter/` and `truth/`), so the interaction is a direct function call with no authentication, tokens, or network boundary. Access control is implicit: `truth.load()` reads `truth.yaml` from the local mounted volume (`DATA_DIR`, default `./data`), a single-user store. The HTTP route that triggers the engine (`POST /api/cover-letter`) also has no auth in the code read.

## Flow  (the sequence of the interaction)

1. Client calls `POST /api/cover-letter` (`api/routes.py::cover_letter`) with `tone`, `length`, and optional `applicationId`.
2. The route requires a prior tailoring step: it reads `data_dir()/"posting.txt"` (written earlier by `/api/tailor`) and 400s if it's missing.
3. The route pulls facts from the **Truth Store** via `truth.load()`, which reads/parses/validates `data/truth.yaml` into a `Truth` object.
4. The route calls `coverletter.build_letter(posting, tone, length, truth, provider)`.
5. Inside `build_letter`:
   - `prompts.cover_letter_facts_block(truth)` renders the truth as the `CANDIDATE FACTS` block; `prompts.cover_letter_system(tone, length)` builds the system prompt instructing the model to tag every factual claim verbatim.
   - `provider.extract_json(...)` returns `{ "paragraphs": [ { "text", "claims": [...] } ] }`.
   - All tagged `claims` are collected and checked with `guardrail.validate([Scope(texts=claims, allowed=_all_values(truth))])`.
   - If `check.ok` is false → returns `{blocked: True, unverifiable, text: ""}`.
   - Otherwise joins paragraph `text` values into the final letter and returns `{blocked: False, ...}`.
6. Back in the route: if blocked, returns `CoverLetterResult(blocked=True, unverifiable=...)`. Otherwise renders HTML (`render.cover_letter.render_letter_html`), optionally attaches to an application, best-effort renders PDF/DOCX, and returns `CoverLetterResult` with URLs and `text`.

Note: the interaction with the Truth Store is read-only here — `build_letter` never writes back. Writes to the store happen on other routes (`/api/extract`, `PUT /api/truth`, `/api/confirm-inferences`).

## Code  (entry points on both sides, with file paths)

**Cover Letter Engine side:**
- `coverletter/generate.py::build_letter` — the entry point; consumes the `Truth` object, prompts the provider, and runs the guardrail. `_all_values(truth)` (same file) is what maps the Truth Store into the allowed-value set.
- `coverletter/__init__.py` — exports `build_letter`.
- `prompts/coverletter.py::cover_letter_facts_block` and `::cover_letter_system` — render the `Truth` into prompt text.
- `api/routes.py::cover_letter` (`POST /api/cover-letter`) — HTTP entry point that wires the store to the engine.
- `api/schemas.py::CoverLetterRequest` / `CoverLetterResult` — the wire contract for that route.

**Truth Store side:**
- `truth/store.py::load` — the function the engine (via the route) calls to obtain the `Truth`; reads/validates `data/truth.yaml`.
- `truth/store.py::data_dir` / `truth_path` — resolve the backing file on the `DATA_DIR` volume.
- `truth/model.py::Truth` (and `Experience`, `Bullet`, `Education`, `Skill`, `Profile`) — the object shape passed across the boundary.
- `truth/__init__.py` — exports `load`, `save`, `Truth`, etc.

**Shared dependency:** `guardrail/validate.py::validate` and `::Scope` — used by the engine to enforce that letter claims stay within Truth Store values.
