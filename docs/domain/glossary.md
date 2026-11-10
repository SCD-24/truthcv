<!-- generated:start cap:glossary-intro -->
# System Intent & Glossary

The overall outcome this system exists to achieve, the canonical component names projected from the architecture canvas, and the authoritative business vocabulary. Treat these terms as carrying their defined meaning throughout the project.
<!-- generated:end cap:glossary-intro -->

<!-- generated:start cap:components-heading -->
## Components

Canonical component names projected from the architecture canvas.
<!-- generated:end cap:components-heading -->

<!-- generated:start comp:web-ui -->
- **Web UI** (`web-ui`) - frontend component. React single-page app (web/) with client-side routing (react-router). Lands on /analytics; the manual CV flow is its own /cv route (Upload LinkedIn PDF → Review extracted truth → Paste job posting (with optional Fetch-from-URL) → Confirm inferences → Download PDF/DOCX), and Applications, Agents, Screenings and Approvals each have their own URL, so a refresh keeps the user where they were. Built by Vite into a static bundle that the API serves (its catch-all returns index.html for deep links). No auth, single-user per deployment.
<!-- generated:end comp:web-ui -->

<!-- generated:start comp:api -->
- **API** (`api`) - backend component. FastAPI backend (truthcv/adapters/http/) that serves the static React bundle and exposes the wizard REST routes. Its route handlers only parse and validate input, call one Services Layer function and translate the result to HTTP; the Services Layer orchestrates the pipeline: PDF upload → truth extraction → job tailoring → guardrail validation → render/download. Configured entirely from env / .env at container start (no secrets entered in the UI). Routes are split into one module per resource (truthcv/adapters/http/*_routes.py) and registered in match order by truthcv/adapters/http/routes.py; request and response models live in the truthcv/adapters/http/schemas/ package. The same process mounts the MCP tool surface from truthcv/adapters/mcp/, the only permitted import between the two adapters.
<!-- generated:end comp:api -->

<!-- generated:start comp:truth-store -->
- **Truth Store** (`truth-store`) - backend component. Owns truth.yaml, the single origin of all facts (truthcv/domain/truth/). Extracts text from an uploaded CV in any supported format — PDF (pypdf), DOCX (python-docx), TXT or Markdown — and builds, validates and persists the structured truth file (every role/company/date/bullet/skill tagged source:uploaded-cv with a stable id). The LLM step that turns that text into a truth file lives in the Services Layer (truthcv/services/truth_extract.py), so truthcv/domain/truth/ imports neither prompts nor providers. Legacy entries tagged linkedin-pdf remain valid. User-confirmed inferences are tagged user-confirmed.
<!-- generated:end comp:truth-store -->


<!-- generated:start comp:guardrail-validator -->
- **Guardrail Validator** (`guardrail-validator`) - backend component. The core truthfulness guardrail (truthcv/engines/guardrail/): a pure, deterministic, scoped token-diff of a draft against truth — no LLM. validate(scopes, global_values) returns ok plus BOTH a flat unverifiable[] token list (back-compat) and structured blocked_claims grouping untraceable tokens under the specific source text (bullet) and scope id they came from, so callers can present whole-claim approve/deny. A token is verifiable if it is a stopword or appears (post-tokenization) in its own scope's allowed set (or the caller-supplied global_values — global skills for CV renders; for cover letters the Cover Letter Engine passes every truth value, including hobbies and the profile header, since a letter weaves the whole career). Render-scoped approvals are passed in by merging an approved claim's text into that scope's allowed set for a single render — the guardrail itself never mutates truth.
<!-- generated:end comp:guardrail-validator -->


<!-- generated:start comp:llm-provider-layer -->
- **LLM Provider Layer** (`llm-provider-layer`) - backend component. Thin LLMProvider abstraction (truthcv/integrations/providers/) with three implementations — anthropic | openai | ollama — selected by the LLM_PROVIDER env var. Interface: complete(system, messages) → str and extract_json(system, messages, schema) → dict. Adding a provider later = one new file; no truthfulness logic depends on which provider is active.
<!-- generated:end comp:llm-provider-layer -->

<!-- generated:start comp:truth-data-volume -->
- **Truth Data Volume** (`truth-data-volume`) - storage component. The single mounted volume (./data) that persists truth.yaml and generated CVs (PDF/DOCX) across container restarts. There is no database — this flat, id-referenced file store is the entire persistence layer.
<!-- generated:end comp:truth-data-volume -->

<!-- generated:start comp:llm-provider-service -->
- **LLM Provider Service** (`llm-provider-service`) - custom component. External LLM inference reached by the provider layer: Anthropic or OpenAI cloud APIs (bring-your-own API key), or a local Ollama container for fully offline use (optional compose profile). Used for PDF→truth extraction, posting keyword extraction, and id-referenced tailoring/rephrasing.
<!-- generated:end comp:llm-provider-service -->

<!-- generated:start cap:system-intent -->
## System Intent

TruthCV is a self-hostable, single-user web application that generates ATS-passing, truthful CVs tailored to a specific job posting. Every fact originates exclusively from a per-user "truth file" (truth.yaml) derived from the user's LinkedIn profile; the app may reword and reorder those facts freely, but any new claim must be explicitly confirmed by the user before it can enter a CV — enforced mechanically by a deterministic guardrail that diffs every factual token against the truth file. It is bring-your-own-API-key, Docker-deployable (docker compose up → localhost:8080), needs no database or accounts, and renders both PDF and DOCX from one ATS-safe source.
<!-- generated:end cap:system-intent -->

<!-- generated:start cap:definitions -->
## Definitions

Authoritative business terms for this system.

### Application

A tracked job application the user is pursuing. Records the submission (company, website, application URL, whether submitted, submission type, outreach status, contact, response, method) and OWNS the CV and cover letter that went out with it. An Application may be General (a portal/no-posting submission) or tied to a specific job posting; it may exist before any document is generated.

**Structure:** id; company; website; applicationUrl; submitted (bool); submissionType (General | Tailored-to-posting); reachedOut (bool); toWho; responseReceived (bool); method (e.g. LinkedIn); optional posting text; owned cvDocument and coverLetterDocument (each: editable source + rendered pdf/docx filenames); createdAt/updatedAt.

### Guardrail

The core truthfulness mechanism: a deterministic post-generation validator that diffs every factual token in a draft CV against the truth file. Any unmatched token is blocked and routed to the confirm-inferences step, making "truthful" a checkable invariant rather than a matter of trust.

### Inference

A claim the tailoring step wants to add that is not already in the truth file (e.g. inferring "Kubernetes" from a GKE role). Every inference is surfaced as an approval checklist item; only user-approved inferences are written back into the truth file (tagged source:user-confirmed) and allowed into a CV.

### Profile

The single-user's personal header on the Truth File: identity and a short self-description, extracted verbatim from the LinkedIn PDF (source:linkedin-pdf) and editable at Review (Step 2). Identity fields (name, email, phone, location, links) are exempt from the Guardrail; the free-text summary is a claim and is validated against the Truth File like any other, so an edited summary that strays from source is blocked at render.

**Structure:** A singleton object: name, email, phone, location, links[] (each label + url), and summary (a short description/headline). Guardrail-exempt: everything except summary.

### Truth File

The per-user truth.yaml: the single, authoritative origin of all facts a CV may contain. Built from the LinkedIn PDF and, later, user-confirmed inferences. The app may reorder/reword its entries but may never introduce a fact not present in it.

**Structure:** A flat list of id-referenced entries; each entry has id, kind (role|company|date|bullet|skill), value, and source (linkedin-pdf | user-confirmed).
<!-- generated:end cap:definitions -->



<!-- generated:start comp:secret-store -->
- **Secret Store** (`secret-store`) - backend component. Neutral encrypted credential/secrets vault (truthcv/infra/secretstore/), extracted from the API to break the api↔providers import cycle. Resolves LLM credentials — reading data/secrets.enc (Fernet, gated on ENCRYPTION_KEY) and falling back to environment variables — and persists them via atomic tmp-rename. A leaf that uses Storage (truthcv.infra.storage data_dir) only for the data path. Depended on downward by both the API and the LLM Provider Layer.
<!-- generated:end comp:secret-store -->


<!-- generated:start comp:application-agent -->
- **Application Agent** (`application-agent`) - backend component. Unattended job-application agent running as its OWN container. Drives a nightly run through the TruthCV MCP tool surface and a remote browser MCP server, screening postings, generating guardrailed CVs and cover letters, submitting applications and writing results back to the ledger. Since the provider-agnostic cutover it is driven by TruthCV's own TypeScript agent harness (agent/harness/) rather than the Claude Code CLI, so it runs on any configured connection - Anthropic, OpenAI, OpenRouter or a local Ollama. The container remains deliberately browserless and has no access to the app data volume.
<!-- generated:end comp:application-agent -->

<!-- generated:start comp:gmail-api -->
- **Gmail / Google OAuth API** (`gmail-api`) - custom component. External Google service used for the Gmail connection: the OAuth 2.0 browser flow (accounts.google.com authorize, oauth2.googleapis.com/token for the PKCE code exchange and refresh-token renewal) and the Gmail REST API (gmail.googleapis.com/gmail/v1/users/me/profile) read to identify the connected mailbox. Reached over HTTPS with httpx from truthcv/integrations/connections/auth/gmail.py; tokens are persisted via the Secret Store.
<!-- generated:end comp:gmail-api -->








<!-- generated:start comp:browser-service -->
- **Browser Service** (`browser-service`) - backend component. The containerised headful Chromium (browser/ container, served by @playwright/mcp). The Application Agent drives it over in-network HTTP MCP. The API reads, opens and closes the operator browser session through its session-control endpoint via truthcv/services/browser.py.
<!-- generated:end comp:browser-service -->




<!-- generated:start comp:jev-api -->
- **Jev (TypeSafe System One) API** (`jev-api`) - custom component. External third-party Jev (TypeSafe) service at https://api.typesafe.ai/v1/systemone. Screening posts job-posting text to it for hard-requirement cross-checks (truthcv/domain/screening/jev.py), invoked from the agent tool surface (_evaluate_jev_criteria) and the API's check_key route.
<!-- generated:end comp:jev-api -->



<!-- generated:start comp:arbeitnow-api -->
- **Arbeitnow Job Board API** (`arbeitnow-api`) - custom component. External public Arbeitnow job-board API (https://www.arbeitnow.com/api/job-board-api). Job Feeds (truthcv/domain/jobfeeds/arbeitnow.py) fetches paginated postings from it on every feed refresh, because arbeitnow is a default, non-removable board (truthcv/domain/agentconfig/boards.py).
<!-- generated:end comp:arbeitnow-api -->

<!-- generated:start comp:application-pipeline -->
- **Application Pipeline** (`application-pipeline`) - backend component. Everything the unattended agent's work is recorded in and judged by: configuration, screening, runs, company research and the application ledger. Five parts:
<!-- generated:end comp:application-pipeline -->

<!-- generated:start comp:document-generation -->
- **Document Generation** (`document-generation`) - backend component. Produces the tailored CV and cover letter from the truth file. Four parts:
<!-- generated:end comp:document-generation -->

<!-- generated:start comp:integrations -->
- **Integrations** (`integrations`) - backend component. Everything that reaches a third-party service on the app's behalf, other than LLM completions. Three parts:
<!-- generated:end comp:integrations -->

<!-- generated:start comp:orchestration -->
- **Orchestration** (`orchestration`) - backend component. All business logic plus the background executor that runs it off the request thread. Two parts:
<!-- generated:end comp:orchestration -->

<!-- generated:start comp:storage -->
- **Storage & Shared Leaves** (`storage`) - backend component. The lowest layer: file storage and the small shared helpers every other component may depend on. Five parts:
<!-- generated:end comp:storage -->
