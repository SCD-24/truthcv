<!-- generated:start edge:tailor-engine→truth-store -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Tailor Engine → Truth Store

- **Participants:** `tailor-engine` → `truth-store`
- **Transport:** `in-process`
<!-- generated:end edge:tailor-engine→truth-store -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The interaction is **in-process Python**, not a network call. The Tailor Engine consumes a read-only `Truth` value object supplied by the caller and reads two persistence helpers from the Truth Store; it never mutates the store itself.

**Input the Tailor Engine receives from the Truth Store** — a `truth.model.Truth` (`truth/model.py`):
- `experiences: list[Experience]` — each has `id`, `role`, `company`, `start`, `end`, `source`, and `bullets: list[Bullet]` (each bullet `id`, `value`, `source`).
- `education: list[Education]` — `id`, `degree`, `school`, `start`, `end`, `source`.
- `skills: list[Skill]` — flat list of `id`, `value`, `source`.
- `profile: Profile` — identity/summary header (not consumed by the Tailor Engine; used later at render).

`source` is constrained to `SOURCE_VALUES = ("linkedin-pdf", "user-confirmed")`; `Truth.validate()` (run on `load()`/`save()`) enforces globally-unique ids across experiences, bullets, education, and skills.

**Output the Tailor Engine produces** — `tailor()` returns `{"keywords": list[str], "inferences": list[dict], "draft": Draft}` and persists the `Draft` to `data_dir()/draft.json` (path obtained from the Truth Store's `data_dir()`).

**Invariants enforced at the Tailor↔Truth boundary** (`tailor/select.py`, `tailor/infer.py`):
- Every draft block carries `source_id` — the id of the truth object it came from. A draft `Experience`/`Education` whose id is not in the loaded `Truth` is **dropped**.
- A bullet id that does not belong to the *same* truth experience is dropped; if a rephrased bullet text is empty, the verbatim truth `bullet.value` is used.
- Header fields (role/company/dates, degree/school) and selected skills are copied **verbatim** from truth — only bullets are rephrased.
- If the provider returns nothing usable, `select_and_rephrase` falls back to all truth verbatim, in original order.
- Inferences represent claims **not** already in truth; each `Inference.experience_id` is coerced to a real truth experience id (or a default of the first experience) — nothing is written back to truth here.

## Auth  (how the interaction is authenticated)

There is **no authentication** between the two components — this is a direct in-process module dependency within a single FastAPI application, not a client/server call. The Tailor Engine imports the Truth Store directly (`from truth.model import Truth`, `from truth.store import data_dir` in `tailor/__init__.py`; `from truth.model import Truth` in `select.py`/`infer.py`) and receives an already-loaded `Truth` object as a function argument.

Trust is instead enforced by **data invariants, not credentials**: `truth.store.validate()` guarantees id uniqueness and valid `source` values, and the Tailor Engine references everything by id so it cannot introduce facts absent from the store. Both sides share the same on-disk data volume, located via `truth.store.data_dir()` (env `DATA_DIR`, default `./data`); no tokens, headers, or keys are involved.

## Flow  (the sequence of the interaction)

1. An HTTP `POST /api/tailor` arrives at `tailor_route` (`api/routes.py`) with a `TailorRequest` body containing `posting`.
2. The route calls `load()` from the Truth Store (`truth/store.py`), which reads `data_dir()/truth.yaml` and returns a validated `Truth` (or `Truth.empty()` if missing/pre-migration shape).
3. The route calls `tailor_engine.tailor(body.posting, truth, provider)` (`tailor/__init__.py`), handing the `Truth` object to the Tailor Engine.
4. Inside `tailor()`: `extract_keywords` runs, then `select_and_rephrase(posting, keywords, truth, provider)` reads the `Truth` to build verbatim-header/rephrased-bullet draft blocks (each keyed by truth `source_id`), then `detect_inferences(keywords, truth, provider)` computes truth-uncovered claims tagged to real experience ids.
5. `tailor()` assembles a `Draft` and persists it to `data_dir()/draft.json` (path from the Truth Store's `data_dir()`), returning `{keywords, inferences, draft}`.
6. The route writes `posting.txt` to the same data volume and returns `TailorResult(keywords, inferences)` to the client. The `draft` stays server-side for later `/api/render`.
7. **Write-back (separate request, not via the Tailor Engine's own store access):** on `POST /api/confirm-inferences`, the route maps approved inference ids to `(experience_id, claim)` via `tailor_engine.claims_for_ids(...)` / validates re-targeted ids with `tailor_engine.valid_experience_ids()` (both reading the saved draft), then calls `truth.extract.write_confirmed(...)` to persist the confirmed claims back into the Truth Store as `user-confirmed` bullets.

## Code  (entry points on both sides, with file paths)

**Tailor Engine (consumer) side:**
- `tailor/__init__.py` — `tailor(posting, truth, provider)` is the main entry; imports `Truth` from `truth.model` and `data_dir` from `truth.store`; also `load_draft`, `save_draft`, `valid_experience_ids`, `claims_for_ids`.
- `tailor/select.py` — `select_and_rephrase(posting, keywords, truth, provider)`: reads `Truth` experiences/education/skills, enforces the id/verbatim invariants.
- `tailor/infer.py` — `detect_inferences(keywords, truth, provider)`: computes claims not present in `Truth`.
- `tailor/model.py` — `Draft`, `DraftExperience`, `DraftEducation`, `Inference` (each block carries `source_id` back to truth).

**Truth Store (provider) side:**
- `truth/__init__.py` — public surface: `load`, `save`, `validate`, `data_dir`, `truth_path`, plus the `Truth`/`Experience`/`Bullet`/… models.
- `truth/store.py` — `load()` (returns a validated `Truth` read from `truth.yaml`), `validate()`, `data_dir()`/`truth_path()`; the `data_dir()` helper is what the Tailor Engine reuses for `draft.json`.
- `truth/model.py` — `Truth` and its members (`Experience`, `Bullet`, `Education`, `Skill`, `Profile`), `SOURCE_VALUES`, `make_id`.
- `truth/extract.py` — `write_confirmed(...)` is the write-back entry used by the API to persist confirmed inferences into truth (invoked from `api/routes.py`, not by the Tailor Engine directly).

**Wiring point (where both meet):**
- `api/routes.py` — `tailor_route` (`POST /api/tailor`) calls `truth.load()` then `tailor_engine.tailor(...)`; `confirm_inferences` (`POST /api/confirm-inferences`) bridges the Tailor Engine's draft lookups to `truth.extract.write_confirmed`.
