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
| **GET** | `/api/runs` | One page of agent runs, newest first. `limit` (default 50; 0 or negative means no limit) and `offset` (default 0, clamped at 0, applied before the limit). Returns {runs, total, limit, offset}; `total` counts every run currently retained, which a capped page cannot report. An offset past the end is an empty page, not an error. Only the 200 most recent runs are retained (runs.store trims on write), so `total` is a count of what is kept, not of every run ever. Read in-process from runs.store on the data volume, not proxied to the supervisor. |
| **GET** | `/api/runs/{run_id}` | One agent run record by id, read in-process from runs.store.get; 404 when unknown. |
| **POST** | `/api/extract` | LLM extracts structured truth.yaml from the uploaded PDF text. |
| **GET** | `/api/truth` | Return the current truth.yaml for the Review step. |
| **PUT** | `/api/truth` | Save user corrections to truth.yaml (Review step); after this it is trusted. |
| **POST** | `/api/tailor` | Extract posting keywords and produce an id-referenced tailored draft; returns any inferences needing confirmation. |
| **POST** | `/api/confirm-inferences` | Approve/reject inferred claims; approved ones are written back into truth.yaml as source:user-confirmed. |
| **POST** | `/api/render` | Guardrail-check the draft then render PDF/DOCX. On block, returns blockedClaims:[{claimId,experienceId,text,tokens[]}] (whole flagged bullets, not loose tokens; keeps unverifiable[] for back-compat). Accepts optional approvals:{approvedClaimIds[],deniedClaimIds[]} — approved claims count as allowed for THIS render only (no truth.yaml write), denied claims are dropped from the draft. |
| **POST** | `/api/cover-letter` | Generate a guardrail-truthful cover letter (tone, length). Returns {blocked, unverifiable, pdfUrl, docxUrl}; blocked if any factual claim fails truth validation. |
| **GET** | `/api/profile` | Saved-profile status ({hasProfile}) so the wizard can offer "use saved profile" and skip re-upload. |
| **GET** | `/api/download/{name}` | Download a rendered artifact (CV/cover-letter PDF or DOCX) by filename. |
| **GET** | `/api/profile/answers` | Return the canonical ATS screening answers stored in truth.answers. |
| **PUT** | `/api/profile/answers` | Partially update the canonical ATS screening answers in truth.answers; returns the merged answers. |
| **POST** | `/api/screenings/deletions` | Delete many screenings in one call; reports per-id outcomes. Operator-only — not an agent route and not an MCP tool. |
| **POST** | `/api/upload` | Upload a CV as PDF, DOCX, TXT or Markdown (multipart); backend extracts text per format and stores the file under its own extension. |
| **GET** | `/api/agent/llm-credentials` | Agent-token-authenticated credential handoff for the unattended agent. Returns provider, wire format, auth type, token, model and base URL for the configured agent route; serves all four connection cards. |
| **PATCH** | `/api/screenings/{screening_id}` | Set one screening's approval decision and/or posting URL. A cover letter is optional — approval no longer requires a drafted letter. |
| **POST** | `/api/auth/{provider}/start` | Begin subscription sign-in for a connection card; returns a paste-code or device-code flow descriptor. |
| **POST** | `/api/auth/{provider}/complete` | Card-generic completion of a paste-code subscription sign-in (supersedes /api/auth/claude/complete, kept as an alias). |
| **POST** | `/api/auth/{provider}/poll` | Perform one non-blocking poll of an in-progress device-code sign-in; returns pending or complete. |
| **GET** | `/api/settings` | Provider settings status (encryptionAvailable, activeProvider, model, *KeySet booleans, ollamaHost). Never returns raw secrets. |
| **POST** | `/api/settings` | Save provider selection + API key/model/host; encrypts to ./data/secrets.enc via ENCRYPTION_KEY. Empty apiKey leaves the stored key unchanged. |
| **POST** | `/api/settings/test` | Test connection: a tiny live provider call with saved/submitted credentials. Returns {ok, detail}. |
| **POST** | `/api/models` | List available models for a provider (live model-list lookup). |
| **POST** | `/mcp` | Streamable-HTTP JSON-RPC MCP tool surface (agenttools/mcp_app.py) used by the Application Agent container; in-network only. |
| **GET** | `/api/screenings` | Every screening record, most recent first; optional ?approval= narrows to the queue. |
| **POST** | `/api/screenings` | Create a screening record from client-supplied fields. |
| **PATCH** | `/api/screenings/approvals` | Apply one approval decision to many screenings; reports per-id outcomes. |
| **PATCH** | `/api/screenings/{screening_id}` | Set one screening's approval decision and/or posting URL (approval requires a drafted letter). |
| **DELETE** | `/api/screenings/{screening_id}` | Delete a screening record. |
| **GET** | `/api/screenings/{screening_id}/letter` | The screening's current cover-letter draft. |
| **POST** | `/api/screenings/{screening_id}/letter` | Draft the letter for one screening, guardrailed; 422 when blocked. |
| **PUT** | `/api/screenings/{screening_id}/letter` | Save the operator's own letter text verbatim and unvalidated (source=operator). |
| **GET** | `/api/cooldown` | Whether a company (optionally narrowed by role) is currently in cooldown. |
<!-- generated:end comp:api -->

## Provider connections API

| Method | Path | Description |
|---|---|---|
| **GET** | `/api/auth/status` | Status of every catalog connection card. Returns `{encryptionAvailable, connections:[{provider,label,modes,subscriptionConnected,apiKeyConnected,authMode,expiresAt,connectedAt}]}`. |
| **POST** | `/api/auth/{provider}/start` | Start the paste-code OAuth flow for a provider — Stage 1 supports this for `claude` only (400 for any other provider). Returns `{flow:"paste-code", authUrl}`. |
| **POST** | `/api/auth/claude/complete` | Complete the Claude paste-code OAuth flow (authorization code → token); stores encrypted via ENCRYPTION_KEY. |
| **POST** | `/api/auth/{provider}/key` | Save an API key (or, for `ollama`, a base URL/bearer token) for a provider connection — probes it live before persisting. Distinct from the paste-code OAuth flow above: this is key/URL storage, not subscription sign-in. An empty body re-validates the currently stored credential without changing it. |
| **GET** | `/api/auth/{provider}/models` | List available models for an authenticated provider connection (live model-list lookup). |
| **POST** | `/api/auth/{provider}/test` | Test connection to an authenticated provider (small live call). Returns {ok, detail}. |
| **POST** | `/api/auth/{provider}/logout` | Revoke provider connection (`mode=subscription` clears OAuth; default `mode=apikey` clears key material). |
| **GET** | `/api/agent/llm-credentials` | Fetch LLM credentials and model for the unattended agent. **Internal, X-Agent-Token guarded.** Returns `{authType, token, model}` or 404 if token is absent or invalid. |

## Model routing API

| Method | Path | Description |
|---|---|---|
| **GET** | `/api/routing` | Get current model routing (tasks, agent, default); each has {connection, model}. |
| **PUT** | `/api/routing` | Update routing (merge only sent fields onto stored state); all connections must exist. A field explicitly sent as `null` clears it — `default`/`agent` sent as null removes that route, and a `tasks` entry sent as null removes that task's route. An absent field is left untouched. |

<!-- generated:start comp:application-agent -->
## Application Agent (`application-agent`)

| Method | Path | Description |
|---|---|---|
| **POST** | `/run` | Trigger a run immediately, fire-and-forget. Requires X-Agent-Token matching AGENT_API_TOKEN. |
| **GET** | `/status` | {running, lastStartedAt, lastFinishedAt, lastExitCode}. Requires X-Agent-Token. |
<!-- generated:end comp:application-agent -->
