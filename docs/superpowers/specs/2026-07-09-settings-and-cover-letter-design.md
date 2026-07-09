# TruthCV — Encrypted Settings & Cover Letters (Design Spec)

Date: 2026-07-09
Status: Approved (design). Next step: implementation plan (writing-plans skill).

This spec extends the existing, working TruthCV backend + wizard. It adds three
capabilities:

1. Encrypted, UI-managed provider API keys (with an `ENCRYPTION_KEY` in `.env`).
2. Cover-letter generation, guardrail-truthful like the CV.
3. Persisted uploaded profile (PDF + parse) and per-posting regeneration.

No new architecture components. All new API surface lands on the existing `api`
component; one new config var (`ENCRYPTION_KEY`). All persistence is on the
existing `./data` volume.

---

## Feature 1 — Encrypted API-key settings

### Storage model (approved: A)
- `.env` holds ONLY `ENCRYPTION_KEY` (a Fernet key). No raw provider keys in `.env`.
- Provider API keys are entered in the Settings UI, sent to the backend,
  encrypted with the master key, and written to `./data/secrets.enc`.
- Decrypted on each provider call.
- **Key resolution order for provider credentials:** `secrets.enc` (if the
  master key is valid) → environment variable fallback.

### Crypto
- Library: `cryptography` — **Fernet** (AES-128-CBC + HMAC, authenticated,
  tamper-detecting). No hand-rolled crypto.
- `ENCRYPTION_KEY` is a URL-safe base64 32-byte Fernet key.
- Helper: `python -m api.genkey` prints a fresh key. Documented in `.env.example`.

### `secrets.enc` contents (plaintext shape, before encryption)
```json
{
  "activeProvider": "anthropic",
  "anthropicApiKey": "sk-ant-...",
  "openaiApiKey": "sk-...",
  "ollamaHost": "http://localhost:11434",
  "model": ""
}
```
Only this file is encrypted. `profile.pdf`, `source.txt`, `truth.yaml`,
`draft.json` remain plain files.

### Missing / invalid `ENCRYPTION_KEY` (approved: A)
- Secrets feature disabled gracefully. Settings modal shows
  "Set ENCRYPTION_KEY in .env first."
- App still runs; provider credentials fall back to environment variables.

### API
- `GET /api/settings` → status only, NEVER returns raw secrets:
  `{ encryptionAvailable: bool, activeProvider, model, anthropicKeySet: bool,
     openaiKeySet: bool, ollamaHost }`.
- `POST /api/settings` → body `{ activeProvider, apiKey?, model?, ollamaHost? }`.
  Empty/omitted `apiKey` = leave the stored key unchanged. Encrypts + writes
  `secrets.enc`. Returns the same status shape as GET.
- `POST /api/settings/test` → performs a tiny live provider call with the
  currently-saved (or just-submitted) credentials; returns
  `{ ok: bool, detail: string }`.

### UI
- ⚙ **Settings** button added to the footer bar; opens a **modal** (not a wizard
  step).
- Fields: Provider dropdown (Anthropic / OpenAI / Ollama); API key (password-
  masked, placeholder shows `••••• set` when a key already exists, empty =
  unchanged; the raw key is NEVER sent back to the browser); Model (optional,
  blank = provider default); Host (Ollama only, in place of API key).
- Actions: **Save** (`POST /api/settings`), **Test connection**
  (`POST /api/settings/test`, shows ok/error inline).

---

## Feature 2 — Cover letters

### Truthfulness (approved: A, two-tier)
- The LLM produces the letter as structured factual **claims** + connective
  **glue** prose.
- Only the factual claims (employers, titles, dates, metrics, skills,
  achievements) are validated by the existing guardrail token-diff against the
  truth store + approved inferences. Connective narrative is allowed freely.
- If any claim is unverifiable: `blocked = true` + `unverifiable` list, and
  NOTHING is rendered — identical contract to CV render.

### Assembly
- Provider call returns e.g. `{ paragraphs: [ { text, claims: [claimText...] } ] }`
  or `{ claims: [...], body: "..." }` — implementer picks the shape; the
  invariant is that every factual claim string is guardrail-checked before the
  letter is assembled and rendered.
- Render to **PDF + DOCX** via the existing `render/` module (a cover-letter
  Jinja template), guardrail-gated, with download URLs under `/api/download/`.

### API
- `POST /api/cover-letter` → body `{ tone, length }` (posting + truth already
  persisted). Returns `{ blocked, unverifiable, pdfUrl, docxUrl }`.

### UX (approved: A — no new wizard step)
- Rail stays 5 steps: Upload → Review → Posting → Confirm → Download.
- On the **Download** step, after the CV renders, an "Also generate a cover
  letter" section appears with: **Tone** (Professional / Warm / Concise),
  **Length** (Short / Standard), a Generate button, and PDF/DOCX download links.

---

## Feature 3 — Persisted profile & per-posting regeneration

### Persisted profile (unencrypted, on the data volume)
- Store the uploaded raw PDF as `./data/profile.pdf` and the parse result as
  `./data/source.txt` (the latter already exists via
  `truth.pdf.persist_source_text`).
- `GET /api/profile` → `{ hasProfile: bool, filename?, uploadedAt? }`.
- On wizard load, if a saved profile exists, the Upload step offers
  "Use saved profile" and lets the user skip straight to Review (truth.yaml is
  already populated) — or re-upload to replace it.

### Change posting & regenerate
- The Posting step is editable and re-runnable WITHOUT re-uploading: paste a new
  posting → re-tailor (overwrites `draft.json`) → re-confirm inferences →
  re-render CV → regenerate cover letter. This works per posting.
- Re-tailoring is idempotent w.r.t. the truth store: it never mutates
  `linkedin-pdf` facts; only confirmed inferences append `user-confirmed` facts.

---

## Files touched (anticipated)
- New: `api/secrets.py` (Fernet load/encrypt/decrypt + resolution order),
  `api/genkey.py`, `render/templates/cover_letter.html.j2`,
  `tailor/cover_letter.py` (or `coverletter/`), tests under `tests/`.
- Edited: `api/routes.py` (settings, cover-letter, profile routes),
  `api/schemas.py` (new camelCase models), `api/config.py` (ENCRYPTION_KEY,
  data paths), `providers/{anthropic,openai,ollama}_provider.py` +
  `providers/__init__.py` (read creds via the secrets resolver, not just env),
  `truth/pdf.py` (persist raw profile.pdf), `.env.example`, `requirements.txt`
  (add `cryptography`), Dockerfile if needed.
- Frontend: `web/src/components/SettingsModal.tsx`, footer button in
  `App.tsx`/`shell.css`, `web/src/api/client.ts` + `types.ts` (settings,
  cover-letter, profile), `web/src/steps/UploadStep.tsx` (use-saved-profile),
  `web/src/steps/DownloadStep.tsx` (cover-letter section),
  `web/src/wizard/store.tsx` (saved-profile + cover-letter state).

## Architecture impact
- Spec-level extension of the `api` component only: new endpoints + one config
  var (`ENCRYPTION_KEY`). No new components or connections. This goes through the
  architecture gate (non-structural) before implementation.

## Out of scope (YAGNI)
- Multi-user accounts / auth. Single-user local tool.
- Key rotation UI (regenerate ENCRYPTION_KEY = re-enter provider keys).
- Rich cover-letter editing; only tone/length knobs.
