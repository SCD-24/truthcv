<!-- generated:start edge:renderer→truth-data-volume -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Renderer → Truth Data Volume

- **Participants:** `renderer` → `truth-data-volume`
- **Transport:** `file I/O`
<!-- generated:end edge:renderer→truth-data-volume -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Renderer (`render/`) does not speak an HTTP protocol to the Truth Data Volume. The volume is the filesystem directory resolved by `truth.store.data_dir()` — the path in `DATA_DIR` (default `./data`), mounted in Docker at the fixed in-container path `/app/data` (`docker-compose.yml`). The interaction is a set of filesystem reads/writes into that directory.

**Reads (Renderer input, sourced from the volume):**
- `truth.yaml` is loaded via `truth.store.load()` → a `Truth` object (`experiences`, `education`, `skills`, `profile`). The API route composes a `Draft` (from `tailor`) plus this `Truth`, and passes the `Draft` and profile identity fields into `render_html(...)`. The Renderer itself only receives an already-assembled `Draft` + profile args; the *volume read* happens in the route, not inside `render/`.

**Writes (Renderer output, into the volume):**
- `render_pdf(html, filename="cv.pdf") -> Path` writes a PDF to `data_dir() / filename` (WeasyPrint) and returns the absolute path.
- `render_docx(html, filename="cv.docx") -> Path` writes a scratch `cv.render.html` into `data_dir()`, then runs `pandoc` to produce `data_dir() / filename`, returning the path.
- Filenames are either shared scratch names (`cv.pdf`/`cv.docx`, `cover_letter.pdf`/`cover_letter.docx`) or per-application names from `applications.store.cv_filenames(app_id)` / `cover_letter_filenames(app_id)`.

**Invariants:**
- `data_dir()` calls `mkdir(parents=True, exist_ok=True)`, so the target directory always exists before a write.
- PDF and DOCX are written **best-effort**: if the backend is missing, `render_pdf`/`render_docx` raise `RenderUnavailable` and callers null the corresponding download URL rather than failing (except a pure wizard preview with no attached application, which hard-errors 500).
- Rendering only happens *after* the guardrail (`guardrail.validate`) passes in `/render`; the Renderer adds no facts of its own (`render/__init__.py`, `render/html.py`).
- Returned paths are later exposed only as `/api/download/{name}` (basename only).

## Auth  (how the interaction is authenticated)

There is no authentication on this interaction. The Renderer accesses the volume purely as a local filesystem path (`Path` writes via WeasyPrint / a `pandoc` subprocess); there are no credentials, tokens, or ACLs between `render/` and the volume. Isolation is provided only by the process/container boundary and the Docker volume mount (`${DATA_DIR:-./data}:/app/data`).

The **download** endpoint that serves these volume files (`GET /api/download/{name}` in `api/main.py`) is likewise unauthenticated, but does enforce path-safety: it rejects any `name` containing `/`, `\`, or `..` and 404s when the file is absent, so only files at the top level of `data_dir()` can be read out.

## Flow  (the sequence of the interaction)

1. Client calls `POST /api/render` (`render_route` in `api/routes.py`).
2. The route loads the draft from `tailor` and loads truth from the volume via `truth.store.load()` (reads `data_dir()/truth.yaml`).
3. The route builds guardrail scopes and runs `guardrail.validate(...)`. If it fails, it returns `RenderResult(blocked=True, ...)` and **nothing is written to the volume**.
4. On pass, the route calls `render_html(draft, name=..., contact=..., summary=..., ...)` to produce the ATS-safe HTML string (no volume access yet).
5. Filenames are chosen: per-application (`app_store.cv_filenames(app_id)`) when attaching, else shared `cv.pdf`/`cv.docx`. For an attached render, `app_store.save_cv_document(...)` records the CV first.
6. The route calls `render_pdf(html, pdf_name)` → writes `data_dir()/pdf_name`; then `render_docx(html, docx_name)` → writes a scratch `cv.render.html` and `data_dir()/docx_name`. Each is wrapped in `try/except RenderUnavailable`.
7. Each successfully written path becomes a `/api/download/{path.name}` URL in the `RenderResult`.
8. Later, the client requests `GET /api/download/{name}`; `api/main.py` validates the name, resolves `data_dir()/name`, and streams it back via `FileResponse`.

(The cover-letter path — `POST /api/cover-letter` and the `PUT /applications/{id}/cv` and `.../cover-letter` save routes — follows the same "render HTML → write files to the volume → expose download URLs" shape, reusing `render_pdf`/`render_docx`.)

## Code  (entry points on both sides, with file paths)

**Renderer side (writes to / reads via the volume):**
- `render/pdf.py` — `render_pdf(html, filename)`: `out = data_dir() / filename`; `HTML(string=html).write_pdf(str(out))`. Defines `RenderUnavailable`.
- `render/docx.py` — `render_docx(html, filename)`: writes `data_dir()/cv.render.html`, runs `pandoc` to `data_dir()/filename`.
- `render/html.py` — `render_html(...)`: builds the HTML string that is written (no direct volume I/O).
- `render/__init__.py` — re-exports `render_html`, `lint`, `render_pdf`, `render_docx`.
- `render/cover_letter.py` — `render_letter_html(...)` (used by the cover-letter/render routes; referenced in `api/routes.py`).

**Truth Data Volume side (the volume abstraction and its consumers):**
- `truth/store.py` — `data_dir()` (resolves `DATA_DIR`, default `./data`; `mkdir` on access) and `truth_path()` / `load()` / `save()` for `truth.yaml`. This is the single definition of the volume path used across the app.
- `truth/model.py` — `Truth` / `Experience` / `Education` / `Skill` / `Profile` shapes read from the volume.
- `docker-compose.yml` — maps host `${DATA_DIR:-./data}` to container `/app/data` and sets `DATA_DIR=/app/data`.

**Wiring / API entry points that connect the two:**
- `api/routes.py` — `render_route` (`POST /api/render`), `cover_letter` (`POST /api/cover-letter`), `save_application_cv` (`PUT /api/applications/{app_id}/cv`), `save_application_cover_letter` (`PUT /api/applications/{app_id}/cover-letter`); helpers `_render_to_files`, `_download_url`. These call `render_pdf`/`render_docx` and read truth via `load()`.
- `api/main.py` — `download` (`GET /api/download/{name}`) serves files from `data_dir()`.
- `applications/store.py` — `cv_filenames` / `cover_letter_filenames` / `save_cv_document` supply the per-application filenames the Renderer writes under `data_dir()`.
