<!-- generated:start edge:truth-store→truth-data-volume -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Truth Store → Truth Data Volume

- **Participants:** `truth-store` → `truth-data-volume`
- **Transport:** `file I/O`
<!-- generated:end edge:truth-store→truth-data-volume -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The `truth-store` (`truth/store.py`) is the persistence layer; the `truth-data-volume` is the mounted `DATA_DIR` directory (host `${DATA_DIR:-./data}` → in-container `/app/data`, also declared as a Docker `VOLUME`). The "contract" is a filesystem one — a fixed set of files inside that volume:

- **`truth.yaml`** — the canonical structured record. Serialized from `Truth.to_dict()` with top-level keys `experiences`, `education`, `skills`, `profile`:
  - `experiences[]`: `{id, role, company, start, end, source, bullets[]}`; each bullet is `{id, value, source}`.
  - `education[]`: `{id, degree, school, start, end, source}`.
  - `skills[]`: `{id, value, source}`.
  - `profile`: `{name, email, phone, location, links[{label,url}], summary}` (identity header, no id/source).
- **`truth.meta.yaml`** — a single-key doc `{source_hash: <sha256>}` fingerprinting the profile source text that produced the current `truth.yaml`.

Invariants enforced by `store.validate()` on every `load()`/`save()`:
- All ids (across experiences, their bullets, education, and skills) are **non-empty and globally unique**; duplicates raise `ValueError`.
- Every `source` must be one of `SOURCE_VALUES = ("linkedin-pdf", "user-confirmed")`; anything else raises `ValueError`.

Read invariants (`store.load()`):
- Missing `truth.yaml` → `Truth.empty()` (no error).
- Legacy/incompatible shapes (a bare list, or a dict containing `entries`, or a dict with none of `experiences`/`education`/`skills`/`profile`) → `Truth.empty()` (fail-safe re-extraction rather than crash).

Write invariants (`store.save()`):
- **Atomic**: writes to `truth.yaml.tmp` then `os.replace()`s it onto `truth.yaml`, so readers never see a partial file. Serialized with `sort_keys=False, allow_unicode=True`.
- `source_hash()` normalizes whitespace before hashing, so trivial reflow of the same profile is not treated as a new source.

## Auth  (how the interaction is authenticated)

There is **no authentication** on this interaction. It is a local filesystem access, not a network call. Access is governed only by:
- **Path binding**: `store.data_dir()` resolves `DATA_DIR` (default `./data`) and `mkdir(parents=True, exist_ok=True)`s it. In Docker, `DATA_DIR` is pinned to `/app/data` (set in both the Dockerfile `ENV` and the compose `app.environment`), and the host directory is bind-mounted there.
- **OS/container file permissions** of the mounted volume.

(Note: secrets that *are* encrypted — `data/secrets.enc`, gated by `ENCRYPTION_KEY` — belong to the separate secretstore, not to the truth-store ↔ volume interaction.)

## Flow  (the sequence of the interaction)

Extraction / persistence (`truth/extract.py::build_truth_from_text`):
1. Compute `store.source_hash(text)` and call `store.load()` (reads `truth.yaml` from the volume).
2. If a non-empty truth is present **and** `store.loaded_source_hash()` (from `truth.meta.yaml`) equals the source hash → return cached truth, no LLM call, no writes.
3. Otherwise call the provider to extract JSON, build a `Truth` (tagging all facts `source='linkedin-pdf'`, assigning stable unique ids).
4. `store.save(truth)` → `validate()` → atomic temp-write + replace onto `truth.yaml`.
5. `store.persist_source_hash(text)` → write `truth.meta.yaml` so a future identical source skips the LLM.

User-confirmed edits (`truth/extract.py::write_confirmed`):
1. `store.load()` the current truth from the volume.
2. Append each new claim as a bullet (`source='user-confirmed'`) on its target experience.
3. `store.save(truth)` back to the volume (atomically, re-validated).

Read-only consumers (tailor/render/guardrail, and API load endpoints) call `store.load()` to get the current `Truth`; on a missing or legacy file they receive `Truth.empty()`.

## Code  (entry points on both sides, with file paths)

Store side (`truth-store`) — `truth/store.py`:
- `data_dir()` / `truth_path()` / `_meta_path()` — resolve the volume paths (`DATA_DIR`).
- `load()` — read + validate `truth.yaml` (fail-safe to empty).
- `save(truth)` — validate + atomic write of `truth.yaml`.
- `source_hash(text)`, `persist_source_hash(text)`, `loaded_source_hash()` — manage `truth.meta.yaml`.
- `validate(truth)` — id-uniqueness and source-value invariants.
- Model shapes serialized/deserialized here: `truth/model.py` (`Truth`, `Experience`, `Bullet`, `Education`, `Skill`, `Profile`, `Link`, `SOURCE_VALUES`).

Callers into the store: `truth/extract.py` (`build_truth_from_text`, `write_confirmed`, `_cached_for`).

Volume side (`truth-data-volume`) — infrastructure declarations:
- `Dockerfile`: `ENV PORT=8080 DATA_DIR=/app/data` and `VOLUME ["/app/data"]`.
- `docker-compose.yml`: `app.environment` sets `DATA_DIR=/app/data`; `app.volumes` mounts `${DATA_DIR:-./data}:/app/data` (host path from `.env`).
- `.env.example`: documents `DATA_DIR=./data` ("Where truth.yaml and generated CVs are persisted").
- Files this interaction owns on the volume: `data/truth.yaml`, `data/truth.meta.yaml` (the same directory also holds unrelated artifacts like `secrets.enc`, generated CVs/cover letters, and `applications.json`).

Note: the compose file names the volume mapping inline (a bind mount), not a named top-level volume called `truth-data-volume`; the only named volume declared is `ollama`. "truth-data-volume" here refers to the `DATA_DIR`-backed `/app/data` mount that the truth-store reads and writes.
