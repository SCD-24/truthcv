<!-- generated:start edge:cover-letter-engine→renderer -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Cover Letter Engine → Renderer

- **Participants:** `cover-letter-engine` → `renderer`
- **Transport:** `in-process`
<!-- generated:end edge:cover-letter-engine→renderer -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Cover Letter Engine and the Renderer are **in-process Python modules**, not networked services. They do not talk to each other directly; `api/routes.py` orchestrates them, passing the engine's output text into the renderer. The contract is therefore expressed as Python function signatures.

**Cover Letter Engine → its caller (`coverletter.build_letter`)**
- Input: `build_letter(posting: str, tone: str, length: str, truth: Truth, provider: LLMProvider)`.
- Output: a plain `dict` with the invariant shape `{"blocked": bool, "unverifiable": list[str], "text": str}`.
- Invariant: `text` is the empty string `""` whenever `blocked` is `True`; nothing renders in that case. The LLM is asked for a `{"paragraphs": [{"text": str, "claims": [str]}]}` JSON structure (`_SCHEMA`); only the tagged `claims` are guardrail-validated (against every factual value in the `Truth`), while connective prose is free. When all claims verify, paragraphs are joined into `text` with blank-line (`"\n\n"`) separators.

**Caller → Renderer (`render.cover_letter.render_letter_html`)**
- Input: `render_letter_html(text: str, name: str = "Your Name", contact: str = "") -> str`. The routes always call it as `render_letter_html(letter["text"])` (name/contact defaulted).
- Invariant: the renderer **introduces no new facts**. It splits `text` on `"\n\n"` into paragraphs and fills the `cover_letter.html.j2` Jinja template, returning an ATS-plain HTML string. The `"\n\n"` paragraph convention is the shared contract between the two sides.

**Renderer HTML → file backends (`render.pdf.render_pdf`, `render.docx.render_docx`)**
- `render_pdf(html, filename) -> Path` (WeasyPrint) and `render_docx(html, filename) -> Path` (pandoc subprocess), each writing under `DATA_DIR`.
- Invariant: both raise `RenderUnavailable` when their native backend is missing; callers treat this as best-effort (a null download URL), not a hard failure — except a pure preview with no application attached, which 500s if neither format is produced.

**HTTP surface (`POST /api/cover-letter`)** wraps this: request `CoverLetterRequest {tone, length, applicationId?}` and response `CoverLetterResult {blocked, unverifiable, pdfUrl?, docxUrl?, text?, renderUnavailable}` (camelCase wire aliases). Note the HTTP request has **no `posting` field** — the posting is read server-side from `DATA_DIR/posting.txt` (written earlier by `/api/tailor`); a missing file yields HTTP 400.

## Auth  (how the interaction is authenticated)

There is **no authentication** on this interaction.

- Engine↔Renderer is an ordinary in-process function call, so there is nothing to authenticate.
- The enclosing HTTP route `POST /api/cover-letter` (and the related `PUT /api/applications/{id}/cover-letter`) has no `Depends(...)` security dependency, no API-key/bearer check, and no auth middleware. The only middleware registered in `api/main.py` is `CORSMiddleware`.
- The only credentials in the system are the **LLM provider** keys (Anthropic/OpenAI API keys, Ollama host), which the engine uses indirectly via the injected `LLMProvider` (`get_provider()`); these authenticate the app to the model vendor, not the caller to the app. The renderer needs no credentials at all.

## Flow  (the sequence of the interaction)

1. Client calls `POST /api/cover-letter` with `{tone, length, applicationId?}`.
2. `cover_letter()` in `api/routes.py` checks `DATA_DIR/posting.txt` exists (else HTTP 400).
3. It calls `build_letter(posting_text, tone, length, load(), get_provider())`.
4. The engine builds a prompt, calls `provider.extract_json(...)` to get tagged paragraphs, collects the `claims`, and runs the guardrail (`validate`) against all truth values.
5. If any claim is unverifiable → engine returns `{blocked: True, unverifiable: [...], text: ""}`; the route returns `CoverLetterResult(blocked=True, unverifiable=...)` and **the renderer is never invoked**.
6. If verified → engine returns `{blocked: False, text: "<paragraphs joined by \n\n>"}`.
7. The route calls `render_letter_html(letter["text"])`, which splits on `"\n\n"` and renders `cover_letter.html.j2` into an HTML string.
8. The route chooses filenames (per-application via `app_store.cover_letter_filenames(app_id)` when `applicationId` is attached and valid; otherwise the scratch `cover_letter.pdf`/`cover_letter.docx`). If attached, the letter source is persisted first via `save_cover_letter_document`.
9. The route calls `render_pdf(html, pdf_name)` and `render_docx(html, docx_name)` best-effort, converting produced paths into `/api/download/{name}` URLs; `RenderUnavailable` leaves the corresponding URL null.
10. If no application is attached and neither file was produced → HTTP 500. Otherwise the route returns `CoverLetterResult(blocked=False, pdfUrl, docxUrl, text, renderUnavailable)`.

(A parallel flow exists for a hand-edited letter: `PUT /api/applications/{id}/cover-letter` skips the engine entirely — the edited text is trusted — and calls `render_letter_html` + the file backends directly.)

## Code  (entry points on both sides, with file paths)

**Cover Letter Engine (`cover-letter-engine`)**
- `coverletter/generate.py` → `build_letter(posting, tone, length, truth, provider)` — the sole entry point; also defines `_SCHEMA`, `_all_values`, and the guardrail gate.
- `coverletter/__init__.py` → re-exports `build_letter` (`__all__ = ["build_letter"]`).

**Renderer (`renderer`)**
- `render/cover_letter.py` → `render_letter_html(text, name, contact)` — the cover-letter entry point; reuses the Jinja env from `render/html.py` (`_env`).
- `render/templates/cover_letter.html.j2` — the ATS-plain template rendered.
- `render/pdf.py` → `render_pdf(html, filename)` and `RenderUnavailable` — HTML→PDF via WeasyPrint.
- `render/docx.py` → `render_docx(html, filename)` — HTML→DOCX via pandoc subprocess.
- `render/__init__.py` → exports `render_html`, `lint`, `render_pdf`, `render_docx` (note: `render_letter_html` is imported directly from `render.cover_letter`, not via this package export).

**Orchestrator wiring both sides**
- `api/routes.py`:
  - `cover_letter()` (route `POST /api/cover-letter`) — imports `build_letter` and `render_letter_html`, calls the engine then the renderer (approx. lines 500–560).
  - `save_application_cover_letter()` (route `PUT /api/applications/{app_id}/cover-letter`) — renderer-only path for hand-edited text (approx. lines 460–466).
- `api/schemas.py` → `CoverLetterRequest`, `CoverLetterResult`, `SaveCoverLetterRequest`, `SaveDocumentResult` — the HTTP wire models.
