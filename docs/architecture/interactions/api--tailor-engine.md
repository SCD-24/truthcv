<!-- generated:start edge:api→tailor-engine -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: API → Tailor Engine

- **Participants:** `api` → `tailor-engine`
- **Transport:** `in-process`
<!-- generated:end edge:api→tailor-engine -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The API calls the Tailor Engine **in-process** as a Python library (`import tailor as tailor_engine`); there is no network protocol between them. The contract is the function signatures and the persisted `draft.json` on the data volume.

**`tailor(posting: str, truth: Truth, provider: LLMProvider) -> dict`** (`tailor/__init__.py`)
- Input: the raw posting text, the current `Truth` document (loaded by the API via `truth.load()`), and an `LLMProvider`.
- Returns `{"keywords": list[str], "inferences": list[dict], "draft": Draft}`. The route (`/api/tailor`) uses only `keywords` and `inferences` for the wire response (`TailorResult`); `draft` is for internal use and is also persisted.
- Side effect: writes the structured `Draft` to `<data_dir>/draft.json`. Each `inferences[i]` dict is `{id, claim, rationale, experienceId}`, with ids of the form `inf-1`, `inf-2`, ….

**`load_draft() -> Draft | None`** — reads `draft.json`; `None` when no posting has been tailored yet. Used by `/api/render`.

**`valid_experience_ids() -> set[str]`** — the `sourceId`s present in the saved draft's experiences. Used by `/api/confirm-inferences` to validate a client-supplied re-targeted `experienceId`.

**`claims_for_ids(approved_ids: list[str]) -> list[tuple[str, str]]`** — maps approved inference ids to `(experience_id, claim)` from the saved draft's inferences.

**Draft shape** (`tailor/model.py`): `experiences` (each `sourceId, role, company, dates, bullets[]`), `education` (`sourceId, degree, school, dates`), `skills[]`, `keywords[]`, `inferences[]`.

**Invariants enforced inside the engine:**
- Every draft block carries the `source_id` of the truth object it came from (traceability for the guardrail).
- `role/company/dates` and all education/skill values are copied **verbatim** from truth — only bullets are rephrased (`tailor/select.py`).
- Unknown experience ids and bullet ids that don't belong to their experience are **dropped**, not trusted (`select_and_rephrase`).
- Inferences never write to truth; they only *propose* claims not already covered, each tagged with a valid target experience id (falling back to the first experience) (`tailor/infer.py`).
- Deterministic fallback: if the provider returns nothing usable, the draft is verbatim truth in original order.

## Auth  (how the interaction is authenticated)

There is **no authentication** on this interaction. The Tailor Engine is a same-process library call, not a remote service, so no tokens, headers, or credentials cross between `api` and `tailor`.

The FastAPI app itself (`api/main.py`) also has no auth layer — no auth middleware or dependencies are configured; only permissive CORS (`allow_origins` from config, `allow_methods=["*"]`, `allow_headers=["*"]`) is added. The only credential in the flow is the **LLM provider API key**, which the API resolves via `providers.get_provider()` (backed by `api/secrets.py`) and passes into `tailor(...)` as the `provider` argument; that key authenticates the engine's provider calls to Anthropic/OpenAI/Ollama, not the api↔tailor boundary.

## Flow  (the sequence of the interaction)

1. Client `POST /api/tailor` with `{ "posting": "..." }` (`TailorRequest`).
2. `tailor_route` (`api/routes.py`) loads truth (`truth.load()`) and a provider (`providers.get_provider()`), then calls `tailor_engine.tailor(body.posting, truth, provider)`.
3. Inside the engine: `extract_keywords` → `select_and_rephrase` (builds the truth-only draft) → `detect_inferences` (proposes uncovered claims). It assembles a `Draft` and persists it to `draft.json`.
4. The route writes the posting to `<data_dir>/posting.txt` (used later by cover-letter generation) and returns `TailorResult` (`keywords`, `inferences`) to the client. ProviderErrors → HTTP 502; other LLM/SDK failures → 502.
5. Client `POST /api/confirm-inferences` with approved inferences. The route calls `tailor_engine.valid_experience_ids()` to sanity-check each `experienceId` (unknown → dropped to `""`), or falls back to `tailor_engine.claims_for_ids(approved_ids)`; confirmed claims are written to truth via `truth.extract.write_confirmed`.
6. Client `POST /api/render`. `render_route` calls `tailor_engine.load_draft()`; if `None`, returns HTTP 400 ("Tailor a posting before rendering."). Otherwise the draft is turned into guardrail scopes, validated, and only then rendered to HTML/PDF/DOCX.

## Code  (entry points on both sides, with file paths)

**API side (callers):** `api/routes.py`
- `tailor_route` → `POST /api/tailor` — calls `tailor_engine.tailor(...)` and persists `posting.txt`.
- `confirm_inferences` → `POST /api/confirm-inferences` — calls `tailor_engine.valid_experience_ids()` and `tailor_engine.claims_for_ids(...)`.
- `render_route` → `POST /api/render` — calls `tailor_engine.load_draft()`.
- Wire models: `api/schemas.py` (`TailorRequest`, `TailorResult`, `InferenceModel`, `ConfirmInferencesRequest`, `RenderRequest`/`RenderResult`).
- App/router wiring: `api/main.py` (`app.include_router(router)`); provider resolution: `providers.get_provider` + `api/secrets.py`.

**Tailor Engine side (entry points):** package `tailor/`
- `tailor/__init__.py` — public surface: `tailor()`, `load_draft()`, `save_draft()`, `valid_experience_ids()`, `claims_for_ids()`; `draft.json` path helpers.
- `tailor/keywords.py` — `extract_keywords`.
- `tailor/select.py` — `select_and_rephrase` (verbatim-header / id-validation invariants).
- `tailor/infer.py` — `detect_inferences`.
- `tailor/model.py` — `Draft`, `DraftExperience`, `DraftEducation`, `Inference` (serialization to/from `draft.json`).

**Shared dependencies across the boundary:** `truth.model.Truth` / `truth.store.data_dir` (loaded by the API, consumed and persisted-to by the engine) and `providers.base.LLMProvider` (constructed by the API, invoked by the engine).
