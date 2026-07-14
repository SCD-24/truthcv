<!-- generated:start edge:api→renderer -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: API → Renderer

- **Participants:** `api` → `renderer`
- **Transport:** `in-process`
<!-- generated:end edge:api→renderer -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Renderer (`render/`) is an **in-process Python library**, not a separate service — the API imports it directly. The contract is therefore Python function signatures, not a wire format.

**`render_html(draft, name, contact, summary, email, phone, location, links) -> str`** (`render/html.py`)
- Input: a structured `tailor.model.Draft` plus header/identity strings. Returns ATS-safe HTML assembled from the `cv.html.j2` template.
- Invariant (stated in the module docstrings): the renderer **introduces no new facts** — it only arranges the already-approved draft. It renders one block per experience so a date/bullet stays with its job.

**`lint(html, keywords) -> list[{code, message}]`** (`render/ats.py`)
- Pure/deterministic ATS checks on the HTML (tables, multi-column, images, non-standard headings, missing contact block, missing posting keywords). It **warns, never blocks**. The API maps each dict into an `AtsWarning{code, message}`.

**`render_pdf(html, filename="cv.pdf") -> Path`** (`render/pdf.py`) and **`render_docx(html, filename="cv.docx") -> Path`** (`render/docx.py`)
- Write the file under the shared data volume (`truth.store.data_dir()`) and return its `Path`. The API turns the returned `path.name` into a `/api/download/{name}` URL.
- Invariant: if the backend (WeasyPrint for PDF, `pandoc` on `PATH` for DOCX) is missing, they raise `RenderUnavailable` (from `render/pdf.py`) rather than producing a file. Callers must catch this.

**`render_letter_html(text, name, contact) -> str`** (`render/cover_letter.py`) — splits prose on blank lines into paragraphs and renders `cover_letter.html.j2`.

At the HTTP edge, `POST /api/render` accepts `RenderRequest{approvals?, applicationId?}` and returns `RenderResult{blocked, unverifiable, blockedClaims, atsWarnings, pdfUrl, docxUrl, html, renderUnavailable}` (`api/schemas.py`). The hard invariant enforced by the API (not the renderer): **the guardrail runs BEFORE any renderer call; if it fails, nothing is rendered** and the response is `blocked=true` with the unverifiable tokens / blocked claims.

## Auth  (how the interaction is authenticated)

There is **no authentication between the API and the Renderer** — it is a direct Python function call within the same process (`from render import lint, render_docx, render_html, render_pdf` in `api/routes.py`). No network hop, token, or credential is involved. The only shared "trust boundary" is the data volume (`data_dir()`), where rendered files are written and later served by the unauthenticated `GET /api/download/{name}` route in `api/main.py` (which is guarded only by a path-traversal check rejecting `/`, `\`, and `..`). The API's own external auth (LLM provider keys) lives elsewhere (`api/secrets.py`) and is unrelated to the renderer.

## Flow  (the sequence of the interaction)

For `POST /api/render` (`render_route` in `api/routes.py`):

1. API loads the persisted `Draft` (`tailor_engine.load_draft()`); 400 if none ("Tailor a posting before rendering.").
2. API loads the `Truth` store and builds guardrail `Scope`s per draft block (`_render_scopes`), applying any render-scoped `approvals` (approve = allow this text for this render only, never persisted; deny = drop the claim).
3. API calls `guardrail.validate(scopes, global_values=skill_values)`. **This precedes any renderer call.**
   - If it fails: return `RenderResult(blocked=True, ...)` with `unverifiable` tokens and per-claim `blockedClaims`. **The Renderer is never invoked.**
4. On success: API filters denied claims from the draft, then calls `render_html(...)` to build HTML.
5. API calls `render/ats.lint(html, draft.keywords)` → `atsWarnings`.
6. If an `applicationId` is supplied and valid, the API records the CV document first (`app_store.save_cv_document`) so the link persists, using per-application filenames; otherwise it uses scratch names `cv.pdf`/`cv.docx`.
7. API calls `render_pdf(html, name)` then `render_docx(html, name)`, each in a `try/except RenderUnavailable`, turning produced files into `/api/download/{name}` URLs.
8. Availability rule: a pure preview (no application) with neither format produced → **HTTP 500**; an attached render keeps its saved link and reports `renderUnavailable=true` instead.

The cover-letter flow (`POST /api/cover-letter`) is analogous, calling `render_letter_html` then `render_pdf`/`render_docx`. The save-and-render routes (`PUT /applications/{id}/cv`, `.../cover-letter`) skip the guardrail (a manual human edit is trusted) and call `_render_to_files` best-effort.

## Code  (entry points on both sides, with file paths)

**API side (caller):**
- `api/routes.py` — `render_route` (`POST /api/render`), `cover_letter` (`POST /api/cover-letter`), `save_application_cv` (`PUT /api/applications/{app_id}/cv`), `save_application_cover_letter` (`PUT /api/applications/{app_id}/cover-letter`), and the helper `_render_to_files`. Imports: `from render import lint, render_docx, render_html, render_pdf` and `from render.pdf import RenderUnavailable`; `from render.cover_letter import render_letter_html`.
- `api/main.py` — `GET /api/download/{name}` (`download`), which serves the files the renderer wrote to `data_dir()`.
- `api/schemas.py` — wire models: `RenderRequest`, `RenderResult`, `RenderApprovals`, `BlockedClaimModel`, `AtsWarning`, `CoverLetterRequest/Result`, `SaveCvRequest`, `SaveCoverLetterRequest`, `SaveDocumentResult`.

**Renderer side (callee), package `render/`:**
- `render/__init__.py` — public surface: `render_html`, `lint`, `render_pdf`, `render_docx`.
- `render/html.py` — `render_html` (Jinja2 assembly from `Draft`; templates in `render/templates/cv.html.j2`).
- `render/ats.py` — `lint`.
- `render/pdf.py` — `render_pdf` and the `RenderUnavailable` exception (WeasyPrint).
- `render/docx.py` — `render_docx` (pandoc subprocess; re-raises `RenderUnavailable`).
- `render/cover_letter.py` — `render_letter_html` (template `render/templates/cover_letter.html.j2`).

Note: `api/static/assets/index-*.js` is the built React bundle and is unrelated to this module's "render" (a React internal); the browser client is not part of the API↔Renderer boundary.
