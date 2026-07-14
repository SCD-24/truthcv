<!-- generated:start edge:web-ui→api -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Web UI → API

- **Participants:** `web-ui` → `api`
- **Transport:** `HTTP/REST`
<!-- generated:end edge:web-ui→api -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

The Web UI is a React/Vite SPA that talks to the FastAPI backend over JSON REST under the `/api` prefix. The wire contract is **camelCase** on both sides: Pydantic models in `api/schemas.py` use `alias_generator=to_camel` (with `populate_by_name=True`), and the TypeScript interfaces in `web/src/api/types.ts` mirror them field-for-field. All requests/responses are `application/json` except `/api/upload` (multipart) and `/api/download/{name}` (file stream).

Endpoint contract (server route → request body → response model):

| Method & path | Request | Response |
|---|---|---|
| `POST /api/upload` | multipart `file` (PDF) | `204` (no body) |
| `POST /api/extract` | — | `TruthDoc` |
| `GET /api/truth` | — | `TruthDoc` |
| `PUT /api/truth` | `TruthDoc` | `204` |
| `POST /api/tailor` | `TailorRequest {posting}` | `TailorResult {keywords, inferences}` |
| `POST /api/confirm-inferences` | `ConfirmInferencesRequest {approved[], approved_ids[]}` | `204` |
| `POST /api/render` | `RenderRequest {approvals?, applicationId?}` (body optional) | `RenderResult` |
| `GET /api/profile` | — | `ProfileStatus {hasProfile}` |
| `POST /api/cover-letter` | `CoverLetterRequest {tone, length, applicationId?}` | `CoverLetterResult` |
| `GET/POST /api/settings`, `POST /api/settings/test` | `SettingsUpdate` | `SettingsStatus` / `TestResult` |
| `POST /api/models` | `SettingsUpdate` | `ModelList {models}` |
| `GET/POST /api/applications`, `PUT/DELETE /api/applications/{id}` | `ApplicationCreate`/`ApplicationUpdate` | `ApplicationModel` (list / single / `204`) |
| `PUT /api/applications/{id}/cv` | `SaveCvRequest {html}` | `SaveDocumentResult` |
| `PUT /api/applications/{id}/cover-letter` | `SaveCoverLetterRequest {text}` | `SaveDocumentResult` |
| `GET /api/download/{name}` | — | file (PDF/DOCX) |

Key invariants:

- **Guardrail-before-render.** `POST /api/render` runs `guardrail.validate` *before* producing any file. If validation fails, the response is `blocked=true` with `unverifiable` tokens and `blockedClaims[]` (each with a stable `claimId`), and **no file is written**. The UI round-trips per-claim decisions back via `RenderRequest.approvals` (`approvedClaimIds`/`deniedClaimIds`), which apply to that render only and are never persisted to the truth file.
- **Blocked is not an HTTP error.** `blocked`/`renderUnavailable` are `200`-response fields, not error statuses. `renderUnavailable=true` means the source was saved to an application but WeasyPrint/pandoc produced neither PDF nor DOCX (download URLs are `null`); a pure preview (no `applicationId`) instead hard-errors `500`.
- **Manual edits are trusted.** `PUT .../cv` and `PUT .../cover-letter` save human-edited documents as-is; the guardrail only gates AI generation (`/tailor`, `/render`, `/cover-letter`).
- **Download URLs.** `pdfUrl`/`docxUrl` are server-relative paths of the form `/api/download/{name}`, or `null` when the file wasn't produced.
- **Secrets never leave the server.** `SettingsStatus` exposes only booleans/host (`anthropicKeySet`, `openaiKeySet`, `ollamaHost`), never raw API keys.
- **Errors.** On non-2xx, the backend returns `{"detail": "..."}` (FastAPI `HTTPException`); the client extracts `body.detail` as the user-facing message.

## Auth  (how the interaction is authenticated)

**There is no authentication between the Web UI and the API.** TruthCV is a single-user, locally-run tool:

- No auth middleware, `Depends(...)` guard, session, cookie, or bearer token exists on any route in `api/routes.py` / `api/main.py`.
- The client (`web/src/api/client.ts`) sends no `Authorization` header or credential; it only sets `Content-Type: application/json` on bodied requests. `request()` calls `fetch` with no auth wiring.
- CORS is configured in `api/main.py` via `CORSMiddleware` with `allow_origins=cors_origins()` (default `http://localhost:5173`, overridable by `CORS_ORIGINS`), `allow_credentials=True`, and `allow_methods/headers=["*"]`. This governs browser cross-origin access, not user authentication.
- The only "credentials" in play are **LLM provider API keys**, which are a server-side concern: submitted via `POST /api/settings`, encrypted at rest (`secretstore`, gated on `ENCRYPTION_KEY`), and never returned to the browser. They authenticate the API to upstream providers, not the UI to the API.

In production the SPA is served **same-origin** by the API itself (`_mount_static()` mounts the built bundle from `api/static` with SPA fallback), so requests to `/api/...` go to the same host. In dev, Vite proxies `/api` → `http://localhost:8080` (`web/vite.config.ts`).

## Flow  (the sequence of the interaction)

The UI drives a linear wizard (`web/src/steps/*`), each step calling one or more client functions:

1. **Upload (UploadStep)** → `uploadPdf(file)` → `POST /api/upload` (multipart). Server extracts PDF text, caches a source hash, and persists the profile PDF. Then `extractTruth()` → `POST /api/extract` runs an LLM pass over the stored text and returns a `TruthDoc`.
2. **Review (ReviewStep)** → `getTruth()` (`GET /api/truth`) to load facts, then `saveTruth(doc)` (`PUT /api/truth`) to persist user corrections. After this the facts are "trusted."
3. **Posting (PostingStep)** → `tailor(posting)` → `POST /api/tailor`. Server runs the tailoring engine (two sequential model calls), stores `posting.txt`, and returns `keywords` + `inferences`.
4. **Confirm (ConfirmStep)** → `confirmInferences(approved[])` → `POST /api/confirm-inferences`. The user's (possibly edited) claim text and re-targeted `experienceId` are written as `user-confirmed` bullets.
5. **Render / Download (DownloadStep)** → `render(approvals?, applicationId?)` → `POST /api/render`. Server runs the guardrail first:
   - If it fails: `200` with `blocked=true` + `blockedClaims`; the UI shows per-claim approve/deny, then re-calls `render()` with `approvals` (`approvedClaimIds`/`deniedClaimIds`).
   - If it passes: server renders HTML → PDF/DOCX, runs the ATS linter, and returns `atsWarnings`, `pdfUrl`, `docxUrl`, and `html`. The browser downloads via `GET /api/download/{name}`.
6. **Cover letter** → `generateCoverLetter(tone, length, applicationId?)` → `POST /api/cover-letter` (requires a prior tailor so `posting.txt` exists), also guardrail-gated.
7. **Applications tracking** (`web/src/applications`) → `listApplications`/`createApplication`/`updateApplication`/`deleteApplication` (CRUD over `/api/applications`), plus `saveApplicationCv`/`saveApplicationCoverLetter` (`PUT .../cv`, `.../cover-letter`) to attach hand-edited documents. Passing `applicationId` to render/cover-letter routes saves output as that application's owned files.
8. **Settings** (`web/src/settings`) → `getSettings`/`saveSettings`/`testConnection`/`listModels` manage the LLM provider used by all generation routes.

Cross-cutting client behavior (`request()` in `client.ts`): every call aborts after `REQUEST_TIMEOUT_MS = 120_000` ms (generous, since LLM routes take 30s+); a timeout and a connection failure produce distinct user-facing messages; `204` responses resolve to `void`; non-2xx throws an `Error` carrying `detail`.

## Code  (entry points on both sides, with file paths)

**API (server) side:**
- `api/main.py` — FastAPI app: `CORSMiddleware` setup, router inclusion, `GET /api/download/{name}`, and `_mount_static()` which serves the built SPA from `api/static` with SPA fallback. `main()` runs uvicorn on `PORT` (default `8080`).
- `api/routes.py` — `APIRouter(prefix="/api")` with all wizard/application/settings route handlers (`upload`, `extract`, `truth`, `tailor`, `confirm-inferences`, `render`, `cover-letter`, `applications`, `settings`, `models`, etc.).
- `api/schemas.py` — Pydantic request/response models with camelCase aliases (the wire contract).
- `api/config.py` — `cors_origins()`, `port()`, `static_dir()`; re-exports secret config.
- `api/secrets.py` — shim re-exporting the `secretstore` package (credential resolution/storage).

**Web UI (client) side:**
- `web/src/api/client.ts` — typed `fetch` wrappers for every route, plus the shared `request<T>()` helper (timeouts, `204` handling, error extraction). This is the single point through which the UI reaches the API.
- `web/src/api/types.ts` — TypeScript interfaces mirroring `api/schemas.py`.
- `web/src/steps/*` (`UploadStep`, `ReviewStep`, `PostingStep`, `ConfirmStep`, `DownloadStep`, `DocumentEditor`) — wizard step components that call the client functions.
- `web/src/applications/` and `web/src/settings/` — application-tracking and provider-settings UI consuming the corresponding client functions.
- `web/src/App.tsx` / `web/src/main.tsx` — SPA entry points.
- `web/vite.config.ts` — dev proxy (`/api` → `localhost:8080`) and build output into `../api/static`.

*Note: I did not open individual step/settings/applications component files, so their internal call ordering is inferred from the client function docstrings and route semantics; the client and route/schema layers above were read directly.*
