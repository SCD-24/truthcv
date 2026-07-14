<!-- generated:start edge:api→application-tracker -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: API → Application Tracker

- **Participants:** `api` → `application-tracker`
- **Transport:** `in-process`
<!-- generated:end edge:api→application-tracker -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The API (`api`) is an in-process consumer of the Application Tracker (`applications`); the interaction is a Python function-call contract, not a network hop. All JSON shapes below are on the *outer* HTTP edge (`/api/applications*`), while the API↔Tracker boundary itself passes plain `dict`s and returns `Application`/`Document` dataclasses.

**Tracker function contract** (imported as `app_store`, defined in `applications/store.py`):
- `load_all() -> list[Application]` — every record; returns `[]` on a missing/malformed `applications.json` (fails safe, never raises).
- `get(app_id) -> Application | None` — lookup by id.
- `create(fields: dict) -> Application` — only keys in `Application.EDITABLE` are honored (`company, website, application_url, submitted, submission_type, reached_out, to_who, response_received, method, posting, application_date, notes`); everything else (documents, `id`, timestamps) is ignored/managed internally.
- `update(app_id, patch: dict) -> Application | None` — applies whitelisted, non-`None` fields; `None` on unknown id.
- `delete(app_id) -> bool` — removes the record *and* its owned files; `False` if it didn't exist.
- `save_cv_document(app_id, source) -> Application | None` / `save_cover_letter_document(app_id, source) -> Application | None` — attach a `Document(source, pdf_filename, docx_filename)`; `None` on unknown id.
- `cv_filenames(app_id) -> (pdf, docx)` / `cover_letter_filenames(app_id) -> (pdf, docx)` — deterministic per-application names (`cv_{id}.pdf/.docx`, `cover_letter_{id}.pdf/.docx`).

**HTTP contract** (camelCase JSON via `_Camel` alias generator, `api/schemas.py`):
- `GET /api/applications` → `list[ApplicationModel]`, sorted by `created_at` descending.
- `POST /api/applications` (`ApplicationCreate`) → `ApplicationModel`, status 201.
- `PUT /api/applications/{id}` (`ApplicationUpdate`, all fields optional) → `ApplicationModel`; 404 if absent.
- `DELETE /api/applications/{id}` → 204; 404 if absent.
- `PUT /api/applications/{id}/cv` (`SaveCvRequest.html`) / `PUT /api/applications/{id}/cover-letter` (`SaveCoverLetterRequest.text`) → `SaveDocumentResult`; 404 if absent.

**Invariants** enforced across the boundary:
- Documents are never set through `create`/`update`; they are managed only by the `save_*` routes (`_apply_editable` copies only `EDITABLE` fields).
- On a save-and-render, the API records the document **first** (`save_cv_document` / `save_cover_letter_document`), then renders best-effort — so a missing WeasyPrint/pandoc backend can never lose the saved source. `render_unavailable=true` signals "saved but no file produced."
- Manual CV/cover-letter edits are trusted and saved as-is; the truthfulness guardrail only gates automatic generation (`/render`, `/tailor`, `/cover-letter`), not the `save_*` routes.
- `_download_url` nulls a document's `pdf_url`/`docx_url` when the file is absent on the volume, so a recorded filename with no rendered file surfaces as `null`, not a broken link.
- Writes are atomic (`.json.tmp` then `replace`), so a crash mid-write cannot corrupt the list.

## Auth  (how the interaction is authenticated)

There is **no authentication or authorization** on this interaction. The API↔Tracker call is an in-process Python import (`import applications as app_store` in `api/routes.py`), so there are no credentials, tokens, or identity checks between the two.

At the HTTP edge, the FastAPI app (`api/main.py`) adds only CORS middleware (origins from `config.cors_origins()`, `allow_credentials=True`, all methods/headers) — there is no auth dependency, API key, or session guard on any `/api/applications*` route. The application is a single-user local tool; every request operates on the shared `./data` volume with no user scoping. The only request-hardening is path-traversal protection on `GET /api/download/{name}`, and application ids are simply used to build filenames (`new_id()` returns a filename-safe 12-hex-char UUID slice).

## Flow  (the sequence of the interaction)

Typical lifecycle of a tracked application:

1. **Create** — client `POST /api/applications` → `create_application` calls `app_store.create(body.model_dump(...))`; the Tracker mints an id, stamps `created_at`/`updated_at`, appends to `applications.json`, and returns the `Application`, mapped to `ApplicationModel` via `_application_model`.
2. **List / update** — `GET /api/applications` → `app_store.load_all()` (sorted newest-first); `PUT /api/applications/{id}` → `app_store.update(id, patch)` with `exclude_none=True`, 404 if `None`.
3. **Attach a generated document** — from `/render` or `/cover-letter`: if `application_id` is present and `app_store.get(id)` is not `None`, the API resolves per-application filenames via `cv_filenames`/`cover_letter_filenames`, calls `save_cv_document`/`save_cover_letter_document` to persist the source **first**, then renders best-effort to those filenames. Without an `application_id`, output goes to shared scratch files (`cv.pdf`, `cover_letter.pdf`, …) and nothing is saved on the Tracker.
4. **Attach an edited document** — `PUT /api/applications/{id}/cv` or `/cover-letter`: guard existence with `app_store.get(id)` (404 if absent) → `save_*_document` records the source → `_render_to_files` renders best-effort → returns `SaveDocumentResult` with `render_unavailable` reflecting whether a file was produced.
5. **Read back for display** — `_application_model` builds each response; `_document_model` maps stored filenames to download URLs via `_download_url`, which checks the file exists on the volume before emitting `/api/download/{name}`.
6. **Delete** — `DELETE /api/applications/{id}` → `app_store.delete(id)` removes the record and unlinks its owned files (`delete_documents`); 404 if it didn't exist.

## Code  (entry points on both sides, with file paths)

**API side (consumer):**
- `api/routes.py` — imports the Tracker as `import applications as app_store`. Route handlers: `list_applications`, `create_application`, `update_application`, `delete_application`, `save_application_cv`, `save_application_cover_letter`; plus `render_route` and `cover_letter` which optionally attach documents via `application_id`. Mapping helpers: `_application_model`, `_document_model`, `_download_url`, `_render_to_files`.
- `api/schemas.py` — wire models: `ApplicationModel`, `ApplicationCreate`, `ApplicationUpdate`, `ApplicationDocument`, `SaveCvRequest`, `SaveCoverLetterRequest`, `SaveDocumentResult` (and `RenderRequest.application_id`, `CoverLetterRequest.application_id`).
- `api/main.py` — mounts the router and serves rendered files at `GET /api/download/{name}`.

**Application Tracker side (provider):**
- `applications/__init__.py` — public surface re-exported for the API (`create`, `get`, `update`, `delete`, `load_all`, `save_cv_document`, `save_cover_letter_document`, `cv_filenames`, `cover_letter_filenames`, `delete_documents`, plus `Application`, `Document`, `new_id`).
- `applications/store.py` — persistence and document lifecycle against the `./data` volume (`applications.json`, atomic writes).
- `applications/model.py` — `Application` (with `EDITABLE` whitelist) and `Document` dataclasses, `to_dict`/`from_dict`, and `new_id()`.
- Shared dependency: both the Tracker store and the API's download/URL helpers resolve the volume via `truth.store.data_dir()`.
