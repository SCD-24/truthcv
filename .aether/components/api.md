# Component Specification: API
- **Identifier**: `api`
- **Component Type**: BACKEND

> This file is generated dynamically from the spatial architecture canvas. Do not edit directly—use the visual workspaces instead.


## Intent & Scope Description (TEXT)

FastAPI backend (api/) that serves the static React bundle and exposes the wizard REST routes. Orchestrates the pipeline: PDF upload → truth extraction → job tailoring → guardrail validation → render/download. Configured entirely from env / .env at container start (no secrets entered in the UI).

---

## Application routes (ENDPOINTS)

| Method | Endpoint Path | Description & Purpose |
|---|---|---|
| **GET** | `/api/applications` | List all tracked job applications. |
| **POST** | `/api/applications` | Create a new application record. |
| **PUT** | `/api/applications/{id}` | Update an application record (fields and status flags). |
| **DELETE** | `/api/applications/{id}` | Delete an application and its owned document files. |
| **PUT** | `/api/applications/{id}/cv` | Save edited CV content for an application and re-render its pdf/docx (guardrail-checked). |
| **PUT** | `/api/applications/{id}/cover-letter` | Save edited cover-letter content for an application and re-render its pdf/docx. |

---

## Tech Stack Profiles (TECHSTACK)

Supported tools, frameworks, and packages:
- **Python**
- **FastAPI**
- **Uvicorn**

---

## Attach output to an application (NOTE)

> **Attach output to an application**: POST /api/render and POST /api/cover-letter accept an optional applicationId. When present, the rendered output is saved as the named application's owned CV/cover-letter document (per-application filenames, e.g. cv_<appId>.pdf) instead of overwriting the shared cv.pdf/cover_letter.pdf. Absent applicationId preserves today's behavior (scratch preview files). Applications may have no posting (General submissions).

---

## Wizard routes (ENDPOINTS)

| Method | Endpoint Path | Description & Purpose |
|---|---|---|
| **POST** | `/api/upload` | Upload LinkedIn PDF (multipart); backend extracts text with pypdf. |
| **POST** | `/api/extract` | LLM extracts structured truth.yaml from the uploaded PDF text. |
| **GET** | `/api/truth` | Return the current truth.yaml for the Review step. |
| **PUT** | `/api/truth` | Save user corrections to truth.yaml (Review step); after this it is trusted. |
| **POST** | `/api/tailor` | Extract posting keywords and produce an id-referenced tailored draft; returns any inferences needing confirmation. |
| **POST** | `/api/confirm-inferences` | Approve/reject inferred claims; approved ones are written back into truth.yaml as source:user-confirmed. |
| **POST** | `/api/render` | Guardrail-check the draft then render PDF/DOCX. On block, returns blockedClaims:[{claimId,experienceId,text,tokens[]}] (whole flagged bullets, not loose tokens; keeps unverifiable[] for back-compat). Accepts optional approvals:{approvedClaimIds[],deniedClaimIds[]} — approved claims count as allowed for THIS render only (no truth.yaml write), denied claims are dropped from the draft. |
| **POST** | `/api/cover-letter` | Generate a guardrail-truthful cover letter (tone, length). Returns {blocked, unverifiable, pdfUrl, docxUrl}; blocked if any factual claim fails truth validation. |
| **GET** | `/api/profile` | Saved-profile status ({hasProfile}) so the wizard can offer "use saved profile" and skip re-upload. |
| **GET** | `/api/download/{name}` | Download a rendered artifact (CV/cover-letter PDF or DOCX) by filename. |

---

## Editable generated source (NOTE)

> **Editable generated source**: POST /api/render returns the rendered CV HTML as `html`, and POST /api/cover-letter returns the generated letter as `text`. These expose the generated content so the Web UI can pre-fill an editor; the user edits and saves it back via the guardrail-checked PUT /api/applications/{id}/cv (html) and .../cover-letter (text) routes.

---

## Configuration & Environment (CONFIG)

| Key | Example | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `anthropic | openai | ollama` | Which provider implementation to use. |
| `LLM_MODEL` | `claude-3-5-sonnet` | Model id (provider-specific). |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | BYO key, used when LLM_PROVIDER=anthropic. |
| `OPENAI_API_KEY` | `sk-...` | BYO key, used when LLM_PROVIDER=openai. |
| `OLLAMA_HOST` | `http://ollama:11434` | Ollama endpoint, used when LLM_PROVIDER=ollama. |
| `ENCRYPTION_KEY` | `aQ2mA0m3wF6b8xk2s9v0Xr7uY1zC4dN6pQ8rS0tU2w=` | Fernet master key (URL-safe base64, 32 bytes) that encrypts saved provider API keys in ./data/secrets.enc. Generate via `python -m api.genkey`. Missing/invalid disables the secrets feature (falls back to env-var credentials). |
| `STATIC_DIR` | `api/static` | Directory of the built React bundle to serve. |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed CORS origins. |
| `PORT` | `8000` | Port the Uvicorn server binds to. |
| `DATA_DIR` | `./data` | Path to the mounted data volume (truth.yaml, secrets.enc, profile.pdf). |

---

## Settings routes (ENDPOINTS)

| Method | Endpoint Path | Description & Purpose |
|---|---|---|
| **GET** | `/api/settings` | Provider settings status (encryptionAvailable, activeProvider, model, *KeySet booleans, ollamaHost). Never returns raw secrets. |
| **POST** | `/api/settings` | Save provider selection + API key/model/host; encrypts to ./data/secrets.enc via ENCRYPTION_KEY. Empty apiKey leaves the stored key unchanged. |
| **POST** | `/api/settings/test` | Test connection: a tiny live provider call with saved/submitted credentials. Returns {ok, detail}. |
| **POST** | `/api/models` | List available models for a provider (live model-list lookup). |

---

## Render-scoped approvals (no truth write) (NOTE)

> **Render-scoped approvals (no truth write)**: POST /api/render accepts optional approvals:{approvedClaimIds[],deniedClaimIds[]}. On a guardrail block it returns blockedClaims:[{claimId,experienceId,text,tokens[]}] — each a whole draft bullet that tripped the guardrail. Approving a claim makes its text allowed for THAT render only (merged into the matching scope's allowed set before guardrail.validate); denying drops the bullet from the rendered draft. Approvals must NOT be persisted to truth.yaml (write_confirmed is NOT used here) because the user generates many tailored CVs/cover letters from one immutable truth file. claimId is a deterministic hash of experienceId+text so the frontend can round-trip decisions.

---

## Editable inferences at Confirm (NOTE)

> **Editable inferences at Confirm**: POST /api/confirm-inferences accepts approved:[{id, claim, experienceId}] so a user-edited claim (and re-targeted experience) at Step 4 is what gets written as the user-confirmed bullet. approvedIds:[string] is still accepted as a deprecated fallback (writes the original draft claim). write_confirmed persists the supplied claim text verbatim.

---
