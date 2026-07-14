<!-- generated:start group:truthcv-container-single-docker-image -->
# Logical Group: TruthCV Container (single Docker image)
- **Identifier**: `truthcv-container-single-docker-image`
- **Members**: 12

> A logical grouping of components (deployment boundary, bounded context, or scope marker). Groups have no connections of their own.

## Member Components

- **Web UI** (`web-ui`)
- **API** (`api`)
- **Truth Store** (`truth-store`)
- **Tailor Engine** (`tailor-engine`)
- **Guardrail Validator** (`guardrail-validator`)
- **Renderer** (`renderer`)
- **LLM Provider Layer** (`llm-provider-layer`)
- **Truth Data Volume** (`truth-data-volume`)
- **Cover Letter Engine** (`cover-letter-engine`)
- **Prompt Store** (`prompt-store`)
- **Secret Store** (`secret-store`)
- **Application Tracker** (`application-tracker`)

*No specific widgets have been placed in this group yet. Define guidelines, stack tech, or schemas in the workspace.*
<!-- generated:end group:truthcv-container-single-docker-image -->

> _Drafted by Aether from source — not human-verified._

## Rationale

These twelve members form **one deployable unit**: a single Docker image (`Dockerfile`) run as the lone application service in `docker-compose.yml` (`docker compose up` → `localhost:8080`). The image is a two-stage build — stage 1 compiles the **Web UI** (React/Vite/TS in `web/`, output to `api/static` per `vite.config.ts`), stage 2 is a Python 3.11 runtime that copies every backend package (`secretstore/`, `prompts/`, `providers/`, `truth/`, `tailor/`, `guardrail/`, `render/`, `coverletter/`, `applications/`, `api/`) and the built bundle, then runs `python -m api.main`. So the grouping is a **deployment boundary first**: all members share one process, one port, and one filesystem, with no network hops between them (in-process Python imports, not services).

Within that boundary the members are the **bounded contexts that enforce the system intent** — truthful, ATS-passing CVs where every fact traces to `truth.yaml`:

- **API** (`api/main.py`, `api/routes.py`) is the FastAPI host: it serves the built Web UI (SPA fallback in `_mount_static`), exposes the wizard REST routes under `/api`, and streams generated files from the volume via `/api/download/{name}`.
- **Web UI** is the browser wizard (Upload → Review truth → Paste posting → Confirm inferences → Download); in dev it proxies `/api` to `:8080`, in prod it is static assets served by the API.
- **Truth Store** (`truth/`, esp. `store.py`) is the single source of fact: it loads/validates/atomically-saves `truth.yaml` (unique ids, valid sources) and tracks a source hash so extraction can skip repeat LLM passes.
- **Tailor Engine** (`tailor/`) selects/reorders/rephrases truth-only facts against a posting and persists `draft.json`; it also owns keyword extraction and inference detection.
- **Guardrail Validator** (`guardrail/validate.py`) is the mechanical enforcement of the intent: a pure, deterministic, **no-LLM** scoped token diff. `api/routes.py`'s `/render` runs it **before any file is produced** — on failure it returns `blocked=true` with the untraceable claims and nothing renders.
- **Renderer** (`render/`) assembles the approved draft into ATS-safe **PDF and DOCX from one HTML source** (`html.py`, `pdf.py` WeasyPrint, `docx.py` pandoc, `ats.py` lint) — only after the guardrail passes; it adds no facts.
- **Cover Letter Engine** (`coverletter/generate.py`) produces the optional guardrailed cover letter.
- **LLM Provider Layer** (`providers/`) is a thin, swappable abstraction over Anthropic/OpenAI/Ollama (bring-your-own-key); `base.py` explicitly documents that **no truthfulness logic depends on the concrete provider** — providers only *propose* text.
- **Prompt Store** (`prompts/`) is the single home for every system prompt / message builder and shared style fragments.
- **Secret Store** (`secretstore/`, with the `api/secrets.py` shim) is a neutral leaf package resolving credentials from encrypted `secrets.enc` (Fernet) → env; it was extracted specifically so `providers` can get credentials without importing `api` (breaking the only import cycle).
- **Application Tracker** (`applications/`) persists tracked job applications and owns each application's rendered document files.
- **Truth Data Volume** (`truth-data-volume`) is the shared persistence substrate: `DATA_DIR` (default `./data`) mounted at the fixed in-container `/app/data`. Every stateful member writes here — `truth.yaml`/`truth.meta.yaml`, `draft.json`, `posting.txt`, `profile.pdf`/`source.txt`, `applications.json`, `secrets.enc`, and rendered `cv.pdf`/`cv.docx`/`cover_letter.*` — which is what lets the app run with **no database and no accounts** while surviving restarts.

## Notes

- **One container, one port.** `docker-compose.yml` defines a single `app` service on `8080:8080`; the optional `ollama` service is gated behind the `--profile ollama` compose profile and is *not* part of this image. Fully-offline operation uses that separate Ollama container reached over `OLLAMA_HOST` (compose defaults it to `http://ollama:11434`).
- **Volume path discipline.** The container writes to the fixed `/app/data` (set via `DATA_DIR=/app/data` in compose and the `Dockerfile`). The host `.env` `DATA_DIR` (default `./data`) only chooses the *host* mount source — the comment in `docker-compose.yml` warns not to derive the in-container path from the host value.
- **Native rendering deps are baked into the image only.** The `Dockerfile` installs `pandoc`, WeasyPrint's cairo/pango/gdk-pixbuf/libffi, and `fonts-dejavu-core`. Local (non-Docker) dev must install these via the OS package manager or rendering fails. The code degrades gracefully: `render_pdf`/`render_docx` raise `RenderUnavailable`, and routes fall back (attached application saves keep their recorded link even when no file is produced; pure previews hard-error 500).
- **Guardrail-first invariant.** In `/render`, `validate(...)` runs before any file is written; identity fields (name/contact/links) are guardrail-exempt (presentation only), skills are validated globally, and each experience/education/summary block is scoped so a fact from one job can't silently attach to another. Manual human edits (`PUT /applications/{id}/cv` and `.../cover-letter`) are deliberately *trusted and saved as-is* — the guardrail gates only AI generation (`/tailor`, `/render`, `/cover-letter`).
- **State is flat files, written atomically.** Truth Store and Application Tracker both write `.tmp` then `replace` to avoid corruption on crash, and both fail safe on malformed/legacy files (Truth Store returns `Truth.empty()` on the old flat shape; Application Tracker returns `[]`). No database is present anywhere in the grouping.
- **Secrets & Settings modal.** Provider API keys can come from env vars *or* be saved encrypted to `data/secrets.enc` — but the in-app Settings feature only activates when `ENCRYPTION_KEY` is set (Fernet). Resolution order is always `secrets.enc` → environment. `resolve_credentials()` merges stored secrets over env defaults. After a settings write, `reset_provider()` clears the cached provider so the next call re-selects.
- **Provider is cached & swappable.** `providers.get_provider()` memoizes the selected provider (`refresh=True` / `reset_provider()` to rebuild). A `fake`/`FakeProvider` branch exists for tests. `MAX_OUTPUT_TOKENS=16000` is a shared output ceiling; OpenAI is intentionally left uncapped.
- **Frontend serving is dual-mode.** In production the API serves the built bundle from `api/static` with SPA fallback (`_mount_static`); in dev the Vite server on `:5173` proxies `/api` to `:8080`. If the bundle is absent, `main.py` simply skips mounting (API-only).
- **Ports/config surface:** `PORT` (default 8080), `CORS_ORIGINS` (default `http://localhost:5173`), `STATIC_DIR`, plus `LLM_PROVIDER`/`LLM_MODEL`/keys/`OLLAMA_HOST`/`ENCRYPTION_KEY`/`DATA_DIR` from `.env` (see `.env.example`).
