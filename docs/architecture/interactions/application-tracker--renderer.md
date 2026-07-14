<!-- generated:start edge:application-tracker→renderer -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Application Tracker → Renderer

- **Participants:** `application-tracker` → `renderer`
- **Transport:** `in-process`
<!-- generated:end edge:application-tracker→renderer -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Application Tracker (`applications/`) and the Renderer (`render/`) do not talk over the network to each other; they are two Python modules composed **in-process** by the API layer (`api/routes.py`). The "contract" is the function-call boundary the routes bridge, plus the file/JSON invariants each side owns.

**Renderer surface** (`render/__init__.py`) — called by the routes with assembled HTML:
- `render_html(draft, name, contact, summary, email, phone, location, links) -> str` — arranges an approved `tailor.model.Draft` into ATS-safe HTML; adds no new facts.
- `render.cover_letter.render_letter_html(text, name="", contact="") -> str` — cover-letter prose → HTML.
- `render_pdf(html, filename="cv.pdf") -> Path` — writes a PDF under `DATA_DIR`; raises `RenderUnavailable` if WeasyPrint is missing.
- `render_docx(html, filename="cv.docx") -> Path` — writes a DOCX via `pandoc` subprocess under `DATA_DIR`; raises `RenderUnavailable` if pandoc is absent or fails.
- `render.ats.lint(html, keywords) -> list[dict]` — ATS warnings (surfaced separately, not part of the tracker contract).

**Application Tracker surface** (`applications/__init__.py`) — the file names and persisted records the renderer output is attached to:
- `cv_filenames(app_id) -> (f"cv_{app_id}.pdf", f"cv_{app_id}.docx")` and `cover_letter_filenames(app_id) -> (f"cover_letter_{app_id}.pdf", f"cover_letter_{app_id}.docx")` — the tracker **dictates the filenames** the renderer must write to (per-application, so files are retained and traceable).
- `save_cv_document(app_id, source) -> Application | None` / `save_cover_letter_document(app_id, source) -> Application | None` — persist a `Document(source, pdf_filename, docx_filename, updated_at)` onto the application record in `data/applications.json`.
- `get(app_id) -> Application | None`, `delete_documents(app)` (unlinks the owned files).

**Key invariants:**
- **Guardrail before render:** for AI-generated output (`POST /api/render`), `guardrail.validate(...)` runs first; if it fails, **nothing is rendered** and the response is `blocked=true` with `unverifiable`/`blocked_claims`. Manual edits (`PUT /applications/{id}/cv`, `/cover-letter`) are trusted and skip the guardrail.
- **Record-before-render:** when attaching to an application, the routes call `save_*_document` (recording the source and filenames) **before** invoking `render_pdf`/`render_docx`, so the document link always persists even if the render backend is unavailable.
- **Best-effort rendering when attached:** `RenderUnavailable` is swallowed for attached saves; the response sets `render_unavailable=true` and download URLs are `null`. A pure preview (no `application_id`) instead hard-errors with HTTP 500.
- **URL derivation:** `_download_url(name)` returns `/api/download/{name}` only if the file actually exists on the volume; a recorded filename with no produced file yields a `null` URL.
- Wire models are camelCase (`api/schemas.py`); the `Document.source` is the exact editable HTML/text a render was produced from, kept so it can be re-opened and re-rendered.

## Auth  (how the interaction is authenticated)

There is **no authentication** between the two modules and none on the HTTP endpoints that bridge them. Both are in-process Python imports called directly from `api/routes.py`, so no tokens, signatures, or credentials cross the boundary.

At the HTTP edge (`api/main.py`) the only access control is:
- **CORS** (`CORSMiddleware`) restricting browser origins to `CORS_ORIGINS` (default `http://localhost:5173`), with `allow_credentials=True` and wildcard methods/headers.
- **Path-traversal guarding** on the file download route: `GET /api/download/{name}` rejects names containing `/`, `\`, or `..` before serving from `DATA_DIR`.

There are no API keys or auth checks on `/api/render`, `/api/cover-letter`, or the `/api/applications*` routes. (Provider credentials in `secretstore`/`api/secrets.py` authenticate the LLM providers, not this interaction.) This is a single-user, local-volume app.

## Flow  (the sequence of the interaction)

**Attach-on-render (AI-generated CV) — `POST /api/render` in `render_route`:**
1. Load the persisted `Draft` (`tailor_engine.load_draft()`); 400 if none exists.
2. Load the truth, build guardrail `Scope`s per draft block, apply render-scoped approve/deny decisions from `body.approvals`.
3. Run `guardrail.validate(...)`. If it fails → return `RenderResult(blocked=True, ...)` and **stop — nothing is rendered or saved.**
4. On pass: drop denied claims, then `render_html(...)` to produce the CV HTML; compute `lint(...)` ATS warnings.
5. If `body.application_id` is set and `app_store.get(app_id)` exists → resolve per-application filenames via `app_store.cv_filenames(app_id)` and **record the document first** with `app_store.save_cv_document(app_id, html)`. Otherwise use scratch names `cv.pdf`/`cv.docx`.
6. Best-effort `render_pdf(html, pdf_name)` and `render_docx(html, docx_name)`; each `RenderUnavailable` is swallowed and leaves its URL `None`.
7. If not attached and both failed → HTTP 500. Return `RenderResult` with `pdf_url`/`docx_url`, `html`, and `render_unavailable`.

**Attach-on-render (cover letter) — `POST /api/cover-letter`:** same shape — build the letter (guardrail-gated by `coverletter.build_letter`), `render_letter_html`, record via `save_cover_letter_document` first when attached, then best-effort `render_pdf`/`render_docx` to `cover_letter_{app_id}.*`.

**Manual save-and-render — `PUT /api/applications/{app_id}/cv` and `/cover-letter`:** 404 if the app is missing; **no guardrail** (manual edit is trusted); `save_*_document(app_id, source)` records first, then `_render_to_files(html, pdf_name, docx_name)` renders best-effort; response is `SaveDocumentResult` with the updated application and `render_unavailable`.

**Download / cleanup:** the client fetches produced files via `GET /api/download/{name}` (served from `DATA_DIR` in `api/main.py`). `DELETE /api/applications/{app_id}` calls `app_store.delete` → `delete_documents(app)`, which unlinks the renderer-produced `cv_*`/`cover_letter_*` files the application owned.

## Code  (entry points on both sides, with file paths)

**Bridge / route entry points** (where the two modules are composed):
- `api/routes.py` — `render_route` (`POST /api/render`), `cover_letter` (`POST /api/cover-letter`), `save_application_cv` (`PUT /api/applications/{app_id}/cv`), `save_application_cover_letter` (`PUT /api/applications/{app_id}/cover-letter`), plus `_render_to_files`, `_download_url`, `_document_model`. Imports both `from render import lint, render_docx, render_html, render_pdf` (and `render.pdf.RenderUnavailable`, `render.cover_letter.render_letter_html`) and `import applications as app_store`.
- `api/main.py` — `download` (`GET /api/download/{name}`), which serves the renderer's output files.
- `api/schemas.py` — the wire contract: `RenderRequest`/`RenderResult`, `CoverLetterRequest`/`CoverLetterResult`, `SaveCvRequest`/`SaveCoverLetterRequest`/`SaveDocumentResult`, `ApplicationModel`/`ApplicationDocument`.

**Renderer (`renderer`) entry points:**
- `render/__init__.py` — public exports `render_html`, `lint`, `render_pdf`, `render_docx`.
- `render/html.py` — `render_html` (Jinja `cv.html.j2`).
- `render/cover_letter.py` — `render_letter_html`.
- `render/pdf.py` — `render_pdf`, `RenderUnavailable` (WeasyPrint).
- `render/docx.py` — `render_docx` (pandoc subprocess).
- `render/ats.py` — `lint` (ATS warnings).

**Application Tracker (`application-tracker`) entry points:**
- `applications/__init__.py` — public store API (`create`, `update`, `delete`, `get`, `load_all`, `save_cv_document`, `save_cover_letter_document`, `cv_filenames`, `cover_letter_filenames`, `delete_documents`).
- `applications/store.py` — persistence to `data/applications.json` (atomic `.tmp`→replace via `truth.store.data_dir`), filename helpers, and `delete_documents` (unlinks owned files).
- `applications/model.py` — `Application` (with `EDITABLE` whitelist) and `Document` dataclasses.

**Shared location contract:** both sides write/read under `DATA_DIR` via `truth.store.data_dir()` — the renderer writes files there; the tracker records their names and the delete path unlinks them there.
