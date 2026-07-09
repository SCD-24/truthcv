# TruthCV — Design Spec

**Date:** 2026-07-09
**Status:** Approved for planning

## Purpose

A self-hostable web application that generates **ATS-passing, truthful** CVs tailored to a specific job posting. Facts come exclusively from a per-user "truth file" derived from the user's LinkedIn profile; the app may reword and reorder those facts freely, but any new claim must be explicitly confirmed by the user before it enters a CV. The app is bring-your-own-API-key, Docker-deployable, and shareable with anyone who needs it.

## Non-goals

- No user accounts, no shared multi-tenant hosting, no database.
- No automated job-board scraping pipelines; URL fetch is a best-effort convenience only.
- No fancy typographic layout; ATS parseability beats visual polish.

## Users & tenancy

- **Single-user per deployment.** Each person runs their own container (`docker compose up`). No auth, no shared state.
- Intended to be handed to others as an image / repo they run themselves.

## Target output

- **Markets:** Germany (English-language tech CVs) and international/remote. ATS-first English format: single column, no photo, no personal-detail block, standard section headings.
- **Formats:** Both **PDF** and **DOCX**, rendered from one source.

## Architecture

Single Docker image, multi-stage build:

- **Stage 1:** Vite builds the React frontend bundle.
- **Stage 2:** Python + FastAPI serves the static bundle and the API.

Deployment:

- `docker compose up` → app on `localhost:8080`.
- Optional `ollama` compose profile launches a local Ollama container for fully offline use.
- One mounted volume `./data` persists `truth.yaml` and generated CVs across restarts.

## Configuration (env-based)

- `LLM_PROVIDER` — `anthropic` | `openai` | `ollama`
- `LLM_MODEL` — model id (provider-specific; Anthropic defaults to a current Claude model)
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` — as applicable
- `OLLAMA_HOST` — for `ollama` provider (defaults to the compose service or host)
- Keys are read from env / `.env` at container start. Not entered in the UI.

## Provider abstraction

A thin `LLMProvider` interface with three implementations (`anthropic`, `openai`, `ollama`), selected by `LLM_PROVIDER`. Interface:

- `complete(system, messages) -> str`
- `extract_json(system, messages, schema) -> dict` (structured extraction helper)

Adding a provider later = one new file. No truthfulness logic depends on which provider is active.

## Data flow (the wizard)

1. **Upload** LinkedIn PDF → backend extracts text with `pypdf`.
2. **Extract** → LLM produces structured `truth.yaml`: every role, company, date, bullet, and skill, each tagged `source: linkedin-pdf` and given a stable id.
3. **Review** → the extracted truth file is shown in the UI for correction before it is saved. After this step the file is trusted. This is the only place facts originate.
4. **Job input** → a **text box is the primary, always-available input** for pasting raw job-posting text. An optional **"Fetch from URL"** button attempts to retrieve and pre-fill the text box; on any failure it falls back to "paste it instead." No downstream step depends on URL fetch succeeding.
5. **Tailor** → LLM extracts the posting's keywords/requirements, then selects, reorders, and rephrases **only** entries referenced by id from `truth.yaml`.
6. **Confirm inferences** → any claim the LLM wants to add that is not already in `truth.yaml` is surfaced as an approval checklist (e.g., "Add 'Kubernetes' — inferred from your GKE role? [approve]"). Nothing unapproved reaches the CV. Approved items are written back into `truth.yaml` tagged `source: user-confirmed`, so they are trusted on future runs.
7. **Render + download** → PDF and DOCX.

## Truthfulness guardrail (core mechanism)

Mechanical, not discretionary:

- The tailored CV is assembled by **referencing ids** from `truth.yaml`, not by free-generating prose.
- A post-generation **validator diffs every factual token** in the draft against `truth.yaml`. Anything unmatched is blocked and routed to the confirm-inferences step (step 6).
- This makes "truthful" a checkable invariant rather than a matter of trust.

## ATS-safe rendering

One Jinja-templated HTML source →

- **PDF** via **WeasyPrint** (pure-Python, no LaTeX; single column, selectable text, standard headings, small container).
- **DOCX** via **pandoc**.

An **ATS linter** runs before download and warns on: multi-column layouts, tables, text-in-images, non-standard section headings, missing contact block, and posting keywords that appear nowhere in the CV.

## Testing

- Provider layer mocked; no real API calls in CI.
- **Golden tests:** known `truth.yaml` + known posting → assert the tailored output contains only truth-file facts (the guardrail invariant) and passes the ATS linter.
- PDF/DOCX rendering smoke-tested for valid, parseable output.

## Key trade-offs

- **WeasyPrint over LaTeX/Typst:** smaller image, simpler, and ATS output should be plain anyway.
- **`truth.yaml` as a flat, id-referenced store rather than per-CV freeform text:** slight rigidity in exchange for the mechanical truth guarantee that motivates the whole project.
- **Paste-first job input:** robustness against non-standardized job sites; URL fetch is convenience only.

## Component boundaries

- `providers/` — LLM abstraction + three implementations. Depends on: env config. Used by: extraction, tailoring, inference steps.
- `truth/` — parse PDF, build/validate/persist `truth.yaml`. Depends on: pypdf, a provider. Used by: wizard, guardrail.
- `tailor/` — keyword extraction, id-referenced selection, inference detection. Depends on: truth store, a provider.
- `guardrail/` — token diff validator. Depends on: truth store. Pure/deterministic.
- `render/` — Jinja → WeasyPrint (PDF) + pandoc (DOCX) + ATS linter. Depends on: nothing LLM.
- `api/` — FastAPI routes wiring the wizard steps. `web/` — React wizard UI.
