<!-- generated:start edge:api→cover-letter-engine -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: API → Cover Letter Engine

- **Participants:** `api` → `cover-letter-engine`
- **Transport:** `in-process`
<!-- generated:end edge:api→cover-letter-engine -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The interaction is an **in-process Python function call**, not a network hop. The API's `POST /api/cover-letter` route calls `coverletter.build_letter(...)`.

- **HTTP request into the API** (`CoverLetterRequest`, camelCase JSON): `{ "tone": string = "Professional", "length": string = "Standard", "applicationId": string | null }`. The posting itself is *not* in this body — the route reads it from `data/posting.txt` (written earlier by `/api/tailor`), and returns `400` if that file is absent.
- **Call into the engine**: `build_letter(posting: str, tone: str, length: str, truth: Truth, provider: LLMProvider) -> dict`. The route supplies `posting` from the file, `truth` from `truth.load()`, and `provider` from `providers.get_provider()`.
- **Engine return shape**: `{"blocked": bool, "unverifiable": list[str], "text": str}`. Invariant: `text == ""` whenever `blocked is True`; `unverifiable == []` whenever `blocked is False`.
- **Internal LLM contract**: the engine asks the provider for JSON matching `_SCHEMA` — `{"paragraphs": [{"text": str, "claims": [str]}]}` (`text` required, `claims` optional per paragraph).
- **Guardrail invariant** (the core rule): every non-empty `claims` string across all paragraphs is validated against the *global* set of the candidate's truth values (`_all_values(truth)` — every role/company/date/bullet, degree/school/date, and skill). If any claim is unverifiable, the letter is blocked and **no text is returned**. Connective prose (paragraphs without matching claims) is never validated.
- **HTTP response out of the API** (`CoverLetterResult`): when blocked, `{ "blocked": true, "unverifiable": [...] }`. When allowed, `{ "blocked": false, "text": <letter>, "pdfUrl": str|null, "docxUrl": str|null, "renderUnavailable": bool }`. Render URLs may be null if WeasyPrint/pandoc are unavailable; a pure preview (no `applicationId`) hard-errors with `500` in that case, while an attached render keeps its saved link.

## Auth  (how the interaction is authenticated)

There is **no authentication between the API and the Cover Letter Engine** — `coverletter.build_letter` is imported and called directly inside the FastAPI process (`from coverletter import build_letter` in `api/routes.py`), so they share a trust boundary and address space.

The API's own routes are likewise unauthenticated: `api/main.py` mounts CORS (`allow_origins` from `CORS_ORIGINS`, default `http://localhost:5173`) and includes the router, but there is no API-key/token/session middleware on `/api/cover-letter` or any other route. This is a single-user local app.

The only credential in this path is for the **downstream LLM provider**, not for the API↔engine call. The engine receives a `provider` object already constructed by `providers.get_provider()`, whose keys/host come from `secretstore` (encrypted secrets resolved via `api/secrets.py` / `secretstore`). The engine never touches credentials itself.

## Flow  (the sequence of the interaction)

1. Client sends `POST /api/cover-letter` with `tone`, `length`, and optional `applicationId`.
2. `cover_letter()` in `api/routes.py` checks `data/posting.txt` exists (written earlier by `/api/tailor`); if not, returns `400`.
3. The route calls `build_letter(posting_text, body.tone, body.length, load(), get_provider())`.
4. Inside the engine, `build_letter` composes the user message (`POSTING:` + `CANDIDATE FACTS:` via `prompts.cover_letter_facts_block`) and the system prompt via `prompts.cover_letter_system(tone, length)`, then calls `provider.extract_json(...)` against `_SCHEMA`.
5. The engine collects every `claims` token and runs `guardrail.validate([Scope(texts=claims, allowed=_all_values(truth))])`.
6. If validation fails, the engine returns `{"blocked": True, "unverifiable": [...], "text": ""}`; the route maps this to `CoverLetterResult(blocked=True, unverifiable=...)` and returns — nothing is rendered.
7. If validation passes, the engine joins paragraph `text` into the final letter and returns `{"blocked": False, "unverifiable": [], "text": ...}`.
8. Back in the route, the text is rendered to HTML (`render.cover_letter.render_letter_html`), optionally saved onto the application (`applications.save_cover_letter_document`, recorded *before* rendering), and rendered best-effort to PDF/DOCX.
9. The route returns `CoverLetterResult` with `text`, `pdfUrl`/`docxUrl` (download links under `/api/download/...`), and `renderUnavailable`. Provider failures raised in step 4 surface as `502`.

## Code  (entry points on both sides, with file paths)

**API side (caller):**
- `api/routes.py` → `cover_letter(body: CoverLetterRequest)` — handler for `POST /api/cover-letter`; imports and calls `build_letter`, then renders/saves the result.
- `api/schemas.py` → `CoverLetterRequest` and `CoverLetterResult` — the HTTP wire contract.
- `api/main.py` → FastAPI app; mounts CORS and `include_router(router)`; also serves `/api/download/{name}`.
- Supporting: `truth.load()` (truth store), `providers.get_provider()` (LLM), `render.cover_letter.render_letter_html`, `applications.save_cover_letter_document` / `cover_letter_filenames`.

**Cover Letter Engine side (callee):**
- `coverletter/__init__.py` → re-exports `build_letter`.
- `coverletter/generate.py` → `build_letter(posting, tone, length, truth, provider)` (entry point), plus `_all_values(truth)` (the allowed-values set) and `_SCHEMA` (LLM JSON shape).
- Prompts used by the engine: `prompts/coverletter.py` → `cover_letter_system(tone, length)` and `cover_letter_facts_block(truth)` (re-exported via `prompts/__init__.py`).
- Guardrail dependency: `guardrail.validate` / `guardrail.Scope` (imported in `coverletter/generate.py`).
