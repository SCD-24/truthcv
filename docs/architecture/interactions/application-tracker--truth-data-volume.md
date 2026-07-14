<!-- generated:start edge:application-tracker→truth-data-volume -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Application Tracker → Truth Data Volume

- **Participants:** `application-tracker` → `truth-data-volume`
- **Transport:** `file I/O`
<!-- generated:end edge:application-tracker→truth-data-volume -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Application Tracker (`applications/`) is not a network peer of the Truth Data Volume — it is a Python module that persists onto the same on-disk data volume that the `truth` package owns. The "contract" is therefore a **filesystem contract** mediated by `truth.store.data_dir()`.

- **Volume resolver (the shared invariant):** `truth.store.data_dir()` returns `Path(os.environ["DATA_DIR"] or "./data")` and calls `mkdir(parents=True, exist_ok=True)` on every access. This is the single source of truth for where files live. `applications.store` imports `data_dir` directly and never resolves the path itself, so both modules always agree on the volume root. In Docker, `DATA_DIR` inside the container is fixed to `/app/data`, mounted from the host `${DATA_DIR:-./data}` (`docker-compose.yml`).

- **Files the Application Tracker writes to the volume:**
  - `applications.json` — the entire list of `Application` records, one JSON array. Shape per record is `Application.to_dict()` (`applications/model.py`): `id`, `company`, `website`, `application_url`, `submitted`, `submission_type`, `reached_out`, `to_who`, `response_received`, `method`, `posting`, `application_date`, `notes`, plus nested `cv_document` / `cover_letter_document` (each `{source, pdf_filename, docx_filename, updated_at}` or `null`), plus `created_at` / `updated_at`.
  - Per-application rendered documents: `cv_{app_id}.pdf` / `cv_{app_id}.docx` and `cover_letter_{app_id}.pdf` / `cover_letter_{app_id}.docx` (`cv_filenames`, `cover_letter_filenames`). These live alongside `truth`'s own files (`truth.yaml`, `truth.meta.yaml`, `profile.pdf`, `posting.txt`, scratch `cv.pdf`/`cover_letter.pdf`) in the same flat directory.

- **Write invariants:**
  - **Atomic writes.** `_write_all` writes `applications.json.tmp` then `Path.replace()`s it over `applications.json`, mirroring `truth.store.save`'s `.yaml.tmp`→replace, so a crash mid-write cannot corrupt the list.
  - **Fail-safe reads.** `load_all()` returns `[]` on a missing file, `JSONDecodeError`, `OSError`, or non-list JSON — a hand-edited or half-written file never crashes startup.
  - **Ownership.** An `Application` owns its four rendered files; `delete()` calls `delete_documents()` which `unlink()`s them (swallowing `FileNotFoundError`/`OSError`) before removing the record.
  - **Flat namespace, no collision.** Uniqueness is guaranteed by `new_id()` = `uuid4().hex[:12]` embedded in each filename; there is no locking, so concurrent writers to `applications.json` would last-writer-win (single-user app).

- **HTTP wire shapes (Application Tracker's REST surface, `api/schemas.py`):** `ApplicationModel`, `ApplicationCreate`, `ApplicationUpdate`, `ApplicationDocument`, `SaveCvRequest`, `SaveCoverLetterRequest`, `SaveDocumentResult` — camelCase over the wire. Stored `pdf_filename`/`docx_filename` are converted to `/api/download/{name}` URLs by `_download_url`, which returns `None` if the file is absent on the volume (e.g. render backend was unavailable at save time).

## Auth  (how the interaction is authenticated)

There is **no authentication** on this interaction. The Application Tracker reaches the Truth Data Volume by a direct in-process Python call (`from truth.store import data_dir`) and ordinary filesystem I/O — no tokens, credentials, or network boundary are involved. Access is governed only by OS filesystem permissions on the mounted volume.

At the HTTP edge, the `/api/applications*` routes are likewise unauthenticated: the app is a single-user tool. The only auth-adjacent controls are CORS (`allow_origins` from `CORS_ORIGINS`, default `http://localhost:5173`) and a path-traversal guard on the download route (`/api/download/{name}` rejects names containing `/`, `\`, or `..` before joining onto `data_dir()`). Secrets/encryption (`secretstore`, `ENCRYPTION_KEY`) protect LLM provider credentials only, not this module-to-volume interaction.

## Flow  (the sequence of the interaction)

1. **Import-time binding.** `applications/store.py` imports `data_dir` from `truth.store`. Every path it computes (`applications_path()`, document filenames) is rooted at `data_dir()`, which lazily creates the volume directory on first access.

2. **Create/update/delete records** (via `POST/PUT/DELETE /api/applications` → `create`/`update`/`delete`):
   - `load_all()` reads `applications.json` from the volume (or `[]`).
   - The list is mutated in memory (`_apply_editable` copies only whitelisted `EDITABLE` fields; documents are never set through generic writes).
   - `_write_all()` writes `applications.json.tmp` then atomically replaces `applications.json`.
   - On delete, `delete_documents()` unlinks the four owned files from the volume first.

3. **Attach + render a document.** In `/api/render` and `/api/cover-letter` (`api/routes.py`), when a `application_id` is supplied and `app_store.get(app_id)` exists:
   - The route asks the tracker for the per-application filenames (`cv_filenames`/`cover_letter_filenames`).
   - **Record-first ordering:** `save_cv_document` / `save_cover_letter_document` persist the `Document` (source + filenames, with `updated_at`) into `applications.json` *before* rendering, so the saved link survives even if the render backend is missing.
   - `render_pdf` / `render_docx` then write the named `.pdf`/`.docx` files onto the same volume (best-effort; `RenderUnavailable` is swallowed for attached saves).

4. **Read back / serve.** `list_applications`/`_application_model` map stored filenames to `/api/download/{name}` URLs via `_download_url`, which re-checks `(data_dir() / name).exists()` on the volume before returning a URL; missing files yield `null`. The `/api/download/{name}` endpoint in `api/main.py` then streams the file straight from `data_dir()`.

## Code  (entry points on both sides, with file paths)

**Truth Data Volume side (owns the volume root):**
- `truth/store.py` → `data_dir()` — resolves `DATA_DIR` (default `./data`), ensures the directory exists; the shared entry point both packages call.
- `truth/store.py` → `save()` / `load()` / `persist_source_hash()` — sibling writers/readers on the same volume (`truth.yaml`, `truth.meta.yaml`), establishing the atomic `.tmp`→replace pattern the tracker mirrors.
- `api/main.py` → `download()` (`GET /api/download/{name}`) — serves any rendered file from `data_dir()`, the read path for tracker-produced documents.

**Application Tracker side (consumer of the volume):**
- `applications/store.py` — the whole persistence layer: `applications_path()` (= `data_dir() / "applications.json"`), `load_all`, `_write_all`, `create`, `update`, `delete`, `get`, `cv_filenames`, `cover_letter_filenames`, `save_cv_document`, `save_cover_letter_document`, `delete_documents`. This file's `from truth.store import data_dir` is the concrete link between the two components.
- `applications/model.py` — `Application` and `Document` dataclasses defining the on-volume JSON shape and the `EDITABLE` field whitelist.
- `applications/__init__.py` — the module's public API (`load_all`, `get`, `create`, `update`, `delete`, `save_cv_document`, `save_cover_letter_document`, `cv_filenames`, `cover_letter_filenames`, etc.).

**HTTP wiring / callers (where routes drive the interaction):**
- `api/routes.py` — `import applications as app_store`; routes `list_applications`, `create_application`, `update_application`, `delete_application`, `save_application_cv` (`PUT /api/applications/{app_id}/cv`), `save_application_cover_letter` (`PUT /api/applications/{app_id}/cover-letter`), plus the attach-and-render branches in `render_route` and `cover_letter`. Helpers `_download_url` / `_document_model` / `_application_model` translate volume filenames to wire URLs.
- `api/schemas.py` (lines ~205–290) — `ApplicationDocument`, `ApplicationModel`, `ApplicationCreate`, `ApplicationUpdate`, `SaveCvRequest`, `SaveCoverLetterRequest`, `SaveDocumentResult`.
- `docker-compose.yml` — pins in-container `DATA_DIR=/app/data` and mounts the host volume, the deployment-level guarantee that both components resolve to the same directory.
