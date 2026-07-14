<!-- generated:start cap:api-intro -->
# API Reference

Endpoints **declared on the architecture canvas** (`endpoints` widgets) — not extracted from source. Reconciliation against live routes is tooling-owned and will operate inside these same generated blocks.
<!-- generated:end cap:api-intro -->

<!-- generated:start comp:api -->
## API (`api`)

| Method | Path | Description |
|---|---|---|
| **GET** | `/api/applications` | List all tracked job applications. |
| **POST** | `/api/applications` | Create a new application record. |
| **PUT** | `/api/applications/{id}` | Update an application record (fields and status flags). |
| **DELETE** | `/api/applications/{id}` | Delete an application and its owned document files. |
| **PUT** | `/api/applications/{id}/cv` | Save edited CV content for an application and re-render its pdf/docx (guardrail-checked). |
| **PUT** | `/api/applications/{id}/cover-letter` | Save edited cover-letter content for an application and re-render its pdf/docx. |
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
| **GET** | `/api/settings` | Provider settings status (encryptionAvailable, activeProvider, model, *KeySet booleans, ollamaHost). Never returns raw secrets. |
| **POST** | `/api/settings` | Save provider selection + API key/model/host; encrypts to ./data/secrets.enc via ENCRYPTION_KEY. Empty apiKey leaves the stored key unchanged. |
| **POST** | `/api/settings/test` | Test connection: a tiny live provider call with saved/submitted credentials. Returns {ok, detail}. |
| **POST** | `/api/models` | List available models for a provider (live model-list lookup). |
<!-- generated:end comp:api -->
