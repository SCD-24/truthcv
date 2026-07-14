<!-- generated:start cap:glossary-intro -->
# System Intent & Glossary

The overall outcome this system exists to achieve, the canonical component names projected from the architecture canvas, and the authoritative business vocabulary. Treat these terms as carrying their defined meaning throughout the project.
<!-- generated:end cap:glossary-intro -->

<!-- generated:start cap:components-heading -->
## Components

Canonical component names projected from the architecture canvas.
<!-- generated:end cap:components-heading -->

<!-- generated:start comp:web-ui -->
- **Web UI** (`web-ui`) — frontend component. React single-page wizard (web/) that walks the user through Upload LinkedIn PDF → Review extracted truth → Paste job posting (with optional Fetch-from-URL) → Confirm inferences → Download PDF/DOCX. Built by Vite into a static bundle that the API serves. No auth, single-user per deployment.
<!-- generated:end comp:web-ui -->

<!-- generated:start comp:api -->
- **API** (`api`) — backend component. FastAPI backend (api/) that serves the static React bundle and exposes the wizard REST routes. Orchestrates the pipeline: PDF upload → truth extraction → job tailoring → guardrail validation → render/download. Configured entirely from env / .env at container start (no secrets entered in the UI).
<!-- generated:end comp:api -->

<!-- generated:start comp:truth-store -->
- **Truth Store** (`truth-store`) — backend component. Owns truth.yaml, the single origin of all facts (truth/). Extracts text from the uploaded LinkedIn PDF via pypdf, uses a provider to build a structured truth file (every role/company/date/bullet/skill tagged source:linkedin-pdf with a stable id), and builds/validates/persists it. User-confirmed inferences are written back tagged source:user-confirmed.
<!-- generated:end comp:truth-store -->

<!-- generated:start comp:tailor-engine -->
- **Tailor Engine** (`tailor-engine`) — backend component. Tailors a CV to a specific posting (tailor/). Extracts the posting's keywords/requirements via a provider, then selects, reorders, and rephrases ONLY entries referenced by id from truth.yaml. Detects any claim the LLM wants to add that is not already in the truth file and surfaces it as an approval checklist (confirm-inferences step); nothing unapproved reaches the CV.
<!-- generated:end comp:tailor-engine -->

<!-- generated:start comp:guardrail-validator -->
- **Guardrail Validator** (`guardrail-validator`) — backend component. The core truthfulness guardrail (guardrail/): a pure, deterministic, scoped token-diff of a draft against truth — no LLM. validate(scopes, global_values) returns ok plus BOTH a flat unverifiable[] token list (back-compat) and structured blocked_claims grouping untraceable tokens under the specific source text (bullet) and scope id they came from, so callers can present whole-claim approve/deny. A token is verifiable if it is a stopword or appears (post-tokenization) in its own scope's allowed set (or global skills). Render-scoped approvals are passed in by merging an approved claim's text into that scope's allowed set for a single render — the guardrail itself never mutates truth.
<!-- generated:end comp:guardrail-validator -->

<!-- generated:start comp:renderer -->
- **Renderer** (`renderer`) — backend component. Renders the approved CV from one Jinja-templated ATS-safe HTML source (render/): PDF via WeasyPrint (pure-Python, single column, selectable text) and DOCX via pandoc. Runs an ATS linter before download that warns on multi-column layouts, tables, text-in-images, non-standard headings, missing contact block, and posting keywords absent from the CV. No LLM dependency.
<!-- generated:end comp:renderer -->

<!-- generated:start comp:llm-provider-layer -->
- **LLM Provider Layer** (`llm-provider-layer`) — backend component. Thin LLMProvider abstraction (providers/) with three implementations — anthropic | openai | ollama — selected by the LLM_PROVIDER env var. Interface: complete(system, messages) → str and extract_json(system, messages, schema) → dict. Adding a provider later = one new file; no truthfulness logic depends on which provider is active.
<!-- generated:end comp:llm-provider-layer -->

<!-- generated:start comp:truth-data-volume -->
- **Truth Data Volume** (`truth-data-volume`) — storage component. The single mounted volume (./data) that persists truth.yaml and generated CVs (PDF/DOCX) across container restarts. There is no database — this flat, id-referenced file store is the entire persistence layer.
<!-- generated:end comp:truth-data-volume -->

<!-- generated:start comp:llm-provider-service -->
- **LLM Provider Service** (`llm-provider-service`) — custom component. External LLM inference reached by the provider layer: Anthropic or OpenAI cloud APIs (bring-your-own API key), or a local Ollama container for fully offline use (optional compose profile). Used for PDF→truth extraction, posting keyword extraction, and id-referenced tailoring/rephrasing.
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

<!-- generated:start comp:cover-letter-engine -->
- **Cover Letter Engine** (`cover-letter-engine`) — backend component. Guardrailed cover-letter generation (coverletter/). build_letter() asks the LLM (via the provider layer) for a cover letter as tagged paragraphs, each declaring the factual claims it makes. Every claim is validated by the Guardrail Validator against the Truth Store; if any claim is unverifiable the letter is BLOCKED (returns {blocked: true, unverifiable, text: ""}). Otherwise the paragraph text is joined and handed to the Renderer for HTML/PDF/DOCX output. Serves /api/cover-letter together with render/.
<!-- generated:end comp:cover-letter-engine -->

<!-- generated:start comp:prompt-store -->
- **Prompt Store** (`prompt-store`) — backend component. The single home for every LLM prompt in TruthCV (prompts/). A shared, fact-free prompt-template library: style-only fragments (CV_STYLE, LETTER_STYLE), the truth-extraction prompt, tailoring prompts (keyword extraction, missing-qualification inference, CV selection) with truth-block renderers, and cover-letter prompts. A pure leaf that depends downward only on truth.model; imported by truth-store, tailor-engine and cover-letter-engine.
<!-- generated:end comp:prompt-store -->

<!-- generated:start comp:secret-store -->
- **Secret Store** (`secret-store`) — backend component. Neutral encrypted credential/secrets vault (secretstore/), extracted from the API to break the api↔providers import cycle. Resolves LLM credentials — reading data/secrets.enc (Fernet, gated on ENCRYPTION_KEY) and falling back to environment variables — and persists them via atomic tmp-rename. A leaf that uses truth.store.data_dir only for the data path. Depended on downward by both the API and the LLM Provider Layer.
<!-- generated:end comp:secret-store -->

<!-- generated:start comp:application-tracker -->
- **Application Tracker** (`application-tracker`) — backend component. Owns the user's job-application records (applications/) persisted as applications.json on the Truth Data Volume. Each Application tracks a submission (Company, Website, Application URL, Submitted, Submission Type, Reached Out, To Who, Response Received, Method) and OWNS its generated documents: an editable CV and cover letter saved per-application (so old outputs are retained and traceable to the application they went out with). Applications may exist WITHOUT a job posting (General/portal submissions). CRUD helpers use atomic writes mirroring truth/store.py; re-renders edited document content via the Renderer.
<!-- generated:end comp:application-tracker -->
