<!-- generated:start edge:api→truth-store -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: API → Truth Store

- **Participants:** `api` → `truth-store`
- **Transport:** `in-process`
<!-- generated:end edge:api→truth-store -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The `api` layer and the Truth Store interact **in-process** — `api` imports the `truth` package directly and calls its functions; there is no network or serialization boundary between them. The unit exchanged is the `Truth` dataclass (`truth/model.py`), a `web`-facing camelCase mirror of which is the `TruthDoc` schema (`api/schemas.py`).

**`Truth` shape** (`truth/model.py`):
- `experiences: list[Experience]` — each has `id`, `role`, `company`, `start`, `end`, `source`, and `bullets: list[Bullet]` (`id`, `value`, `source`).
- `education: list[Education]` — `id`, `degree`, `school`, `start`, `end`, `source`.
- `skills: list[Skill]` — flat; `id`, `value`, `source`.
- `profile: Profile` — `name`, `email`, `phone`, `location`, `links: list[Link]` (`label`, `url`), `summary`. Profile identity fields carry **no** `id`/`source`.

**Invariants enforced by the store** (`truth.store.validate`, called on every `load()`/`save()`):
- Every object `id` must be non-empty and **globally unique** across experiences, bullets, education, and skills (raises `ValueError("Duplicate truth id …")` / `"empty id"`).
- Every `source` must be one of `SOURCE_VALUES = ("linkedin-pdf", "user-confirmed")` (`truth/model.py`); anything else raises `ValueError`. Header fields (role/company/dates, degree/school) inherit their container's source; only bullets and skills carry their own — a user-confirmed inference becomes a `user-confirmed` bullet.
- `load()` fails safe: a missing file, the legacy flat shape (`{entries: […]}` or a bare list), or a doc with none of `experiences|education|skills|profile` all return `Truth.empty()` rather than raising.
- `save()` writes atomically (temp file + `replace`).

**Conversion at the boundary**: `api/routes.py` converts `Truth` ⇄ `TruthDoc` via `TruthDoc.model_validate(truth.to_dict())` on the way out and `Truth.from_dict(body.model_dump(by_alias=False))` on the way in. A `ValueError` from `save()` is translated to HTTP 400 in `put_truth`.

**Auxiliary persisted state** (all under the data volume): `truth.yaml` (the truth), `truth.meta.yaml` (a whitespace-normalized SHA-256 `source_hash` linking the truth to the profile text it was extracted from), `source.txt`, `profile.pdf`, plus scratch/render outputs (`posting.txt`, `cv.pdf`, etc.).

## Auth  (how the interaction is authenticated)

There is **no authentication between `api` and the Truth Store** — they run in the same Python process and the Truth Store is invoked as a library (`from truth import load, save, …`). Trust is enforced by *provenance*, not identity: every fact is tagged `source` (`linkedin-pdf` for extracted facts, `user-confirmed` for approved inferences), and `truth.store.validate` rejects any unknown source value on load/save. Isolation is single-user and filesystem-scoped: the store writes to `data_dir()` (env `DATA_DIR`, default `./data`).

The only authentication in this stack is between the `api` layer and the outside world/third parties, and it lives entirely outside the Truth Store:
- **HTTP entry**: FastAPI (`api/main.py`) applies only `CORSMiddleware` (origins from `CORS_ORIGINS`); there is no API-key or token check on the `/api/*` routes.
- **LLM providers**: credentials used by `truth.extract.build_truth_from_text` come from the provider layer (`get_provider()`), backed by the encrypted `secretstore`; these authenticate the provider call, not the store access.

## Flow  (the sequence of the interaction)

Extraction path (upload → structured truth):
1. `POST /api/upload` → `truth.pdf.extract_text(bytes)` pulls text; `persist_source_text` writes `source.txt`; `truth.store.persist_source_hash` writes the source fingerprint to `truth.meta.yaml`; `persist_profile` saves `profile.pdf`.
2. `POST /api/extract` → `load_source_text()` reads `source.txt`, then `truth.extract.build_truth_from_text(text, provider)`:
   - `_cached_for(text)` calls `store.load()` and compares `store.loaded_source_hash()` to `store.source_hash(text)`; on a match it returns the persisted truth and **skips the LLM** (no tokens spent).
   - Otherwise it calls `provider.extract_json(..., _EXTRACTION_SCHEMA)`, assigns stable unique ids via `make_id`, tags all facts `source='linkedin-pdf'`, then `store.save(truth)` + `store.persist_source_hash(text)`.
3. Result flows back to `api` as `TruthDoc` and out to the client.

Read/write path:
- `GET /api/truth` → `truth.load()` → `TruthDoc`.
- `PUT /api/truth` → `Truth.from_dict(body)` → `truth.save()` (validates; 400 on `ValueError`).

Confirm-inference path:
- `POST /api/confirm-inferences` → `truth.extract.write_confirmed([(experience_id, claim), …])` → `store.load()`, appends each new claim as a `user-confirmed` `Bullet` on its target experience (falling back to the first experience if the id is stale, skipping empties/duplicates), then `store.save()`.

Consumption path (render/tailor/cover-letter):
- `POST /api/tailor`, `POST /api/render`, `POST /api/cover-letter` all call `truth.load()` to get the authoritative facts. `render_route` builds guardrail `Scope`s from the loaded `Truth` (`_render_scopes`) and validates the draft **before** any file is produced; render approvals/denials are render-scoped only and are **never written back** to the store. `tailor_route` and `cover_letter` also read/write `posting.txt` under `data_dir()`.

## Code  (entry points on both sides, with file paths)

**API side** (`api/`):
- `api/routes.py` — the single caller of the Truth Store. Imports `from truth import load, persist_source_hash, save`, `from truth.extract import build_truth_from_text, write_confirmed`, `from truth.model import Truth`, and `from truth.pdf import extract_text, has_profile, load_source_text, persist_profile, persist_source_text`. Relevant handlers: `upload`, `extract`, `get_truth`, `put_truth`, `confirm_inferences`, `tailor_route`, `render_route`, `cover_letter`; helper `_truth_doc` does the `Truth → TruthDoc` conversion. Several handlers also reach `truth.store.data_dir()` directly for scratch files.
- `api/schemas.py` — the wire mirror: `TruthDoc`, `ExperienceModel`, `BulletModel`, `EducationModel`, `SkillModel`, `ProfileModel`, `LinkModel`.
- `api/main.py` — mounts the router and the `/api/download/{name}` file route; imports `truth.store.data_dir` for the data volume.

**Truth Store side** (`truth/`):
- `truth/__init__.py` — the public surface re-exported to `api`: `load`, `save`, `validate`, `data_dir`, `truth_path`, `persist_source_hash`, `loaded_source_hash`, plus the model classes and `make_id`.
- `truth/store.py` — persistence and invariants: `data_dir`, `truth_path`, `source_hash`, `persist_source_hash`, `loaded_source_hash`, `validate`, `load`, `save`.
- `truth/model.py` — the `Truth`/`Experience`/`Bullet`/`Education`/`Skill`/`Profile`/`Link` dataclasses, `SOURCE_VALUES`, and `make_id`.
- `truth/extract.py` — `build_truth_from_text` (LLM extraction + caching) and `write_confirmed` (append confirmed inferences).
- `truth/pdf.py` — `extract_text`, `persist_source_text`, `load_source_text`, `persist_profile`, `has_profile`.

Note: the interaction is a direct in-process function-call boundary; there is no separately deployed Truth Store service, so no client/server transport code exists between the two.
