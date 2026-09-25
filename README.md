# TruthCV
For the friends I made along the way.

Tailor your CV and cover letter to a job posting — **without inventing anything**.

TruthCV extracts a structured "truth file" from an uploaded CV (every role,
date, bullet and skill tagged to its source), then tailors, reorders and rephrases
**only** facts that already exist. A deterministic guardrail diffs every generated
draft against the truth file: any claim it can't trace back to a real fact is
surfaced for your approval or blocked outright. Nothing unverified reaches the
output.

You can upload your CV as a PDF, DOCX, TXT or Markdown file — a LinkedIn PDF
export is simply the easiest source, since it's already dated and tagged by
section.

## Run it

Double-click a launcher in `scripts/launch` — that's the whole install:

| OS | File |
|---|---|
| macOS | `scripts/launch/truthcv.command` |
| Windows | `scripts/launch/truthcv.bat` |
| Linux | `scripts/launch/truthcv.sh` |

If double-clicking opens the file in a text editor instead of running it
(mostly a Linux file-manager quirk), right-click it and choose "Run as a
Program" (some file managers call this "Execute").

The only prerequisite is [Docker Desktop](https://docs.docker.com/get-docker/),
installed and running (wait for its whale icon to settle before you launch).

The first start takes about ten minutes, because your computer is building
TruthCV — that happens once. Every start after it takes a few seconds. When
it's ready, your browser opens at <http://localhost:5627>.

There is no `.env` to write and no command to type. The rest of setup —
connecting a model provider, uploading your CV, filling in your details —
happens in the browser via onboarding. [`SETUP.md`](SETUP.md) is the same
instructions written for a non-technical user, if you're sending this to
someone else to run.

What the launcher actually does, each time you double-click it:

1. Creates `.env` from [`.env.example`](.env.example) if it doesn't exist yet.
2. Fills in `ENCRYPTION_KEY` and `AGENT_API_TOKEN` if they're blank — never
   overwriting a value already set — backing up any `.env` it modifies.
3. Sets `APP_PORT` (default `5627`); if Docker reports that port already
   allocated, it advances to the next candidate and rewrites `.env`, retrying
   up to 10 times.
4. Runs `docker compose up -d --build`, which starts the app, browser and
   agent containers together.
5. Polls the app until it answers, then opens it in your browser.

**Stopping it:** quit Docker Desktop, or run `docker compose down`. Your data
stays in `./data` either way.

## Connecting a model provider

TruthCV needs an LLM provider to extract, tailor and guardrail your CV, but it
does not require you to bring your own API key. Connect one from **Model routing →
Accounts** (or during onboarding, see below) — TruthCV supports four:

- **Claude (Anthropic)** — sign in with a Claude Pro/Max subscription (OAuth,
  no API key needed), or paste an Anthropic API key.
- **ChatGPT (OpenAI)** — sign in with a ChatGPT subscription using a device code, or paste an OpenAI API key.
- **OpenRouter** — an OpenRouter API key.
- **Ollama** — no credential; point it at a local (or remote) Ollama URL.

Connecting an account supplies credentials; it does **not** select the provider
used for CV tasks. Choose a **Default model** separately under **Model routing**;
optional per-task overrides for truth extraction, keywords, tailoring,
inference and cover letter generation take priority, and cleared tasks use the
default. Without a saved route, provider selection preserves any migrated
provider choice from an older installation, then falls back to `LLM_PROVIDER`
in `.env`. Save a new Default model to override that migrated choice.
Credentials for a selected connection come from the saved sign-in or
API key (encrypted at rest in `./data/secrets.enc`), with the corresponding
environment credential as fallback when no saved credential is available.

Routing choices autosave when you change them; account sign-ins, API keys and
Ollama URLs still require their explicit Connect/Save action. Incomplete custom
models stay as unsaved drafts, and failed saves show
an error with Retry. Leaving the page keeps drafts and flushes pending edits;
a warning protects unresolved changes before closing the tab. To abandon them,
use **Discard routing changes**; an in-flight write finishes before a fresh
routing reload, and routing edits remain locked until that reload succeeds.
The independent **Application agent** route governs unattended browser
applications on the next run; clearing it uses Claude, not the default task
model, with saved Claude sign-in/API key and environment credential fallback.

### Onboarding

The first time you open TruthCV, a guided onboarding flow (rather than the
main app) greets you: it walks you through connecting a provider and
uploading/reviewing your CV, skipping any step you've already completed, then
hands off into a short guided tour of the app. You only see it until those
steps are satisfied.

## What's in the app

TruthCV is a multi-page app, not a single linear wizard:

- **Analytics** — the landing page, with side navigation to everything else.
- **Applications** — the job-application ledger (see below), including Gmail-derived employer-reply suggestions when [Gmail response tracking](#gmail-response-tracking-optional) is connected.
- **Screenings & Approvals** — screened postings awaiting your decision,
  including cover-letter approvals and cooldowns before an already-skipped
  company is reconsidered.
- **Company research** — background TruthCV has gathered on a company, with
  its source recorded alongside each fact.
- **Agents** — the unattended agent's run history, schedule, target companies
  and job boards, and site sign-ins.
- **Model routing** — provider accounts, the default and task model routes, and
  the independent application-agent model route.

Documents are checked twice: the guardrail approves the *content* before
rendering, and a separate verification pass (`render/verify.py`) extracts text
back out of the *produced PDF* and compares it against what was meant to be
there — a font/kerning defect that glues or drops words in the PDF surfaces as
an ATS warning, even though the source HTML was fine.

## Application tracker

Beyond generating documents, TruthCV keeps a ledger of every job you're
pursuing. The **Applications** page records each submission — company, dates,
links, status (submitted / reached out / response received), method, notes and
the job posting — and lets you attach the exact CV and cover letter that went
out with it.

**Export** downloads the whole ledger as a single `applications.zip`:

- `applications.csv` — every tracked application as a row, with all its fields.
- One folder per company, holding that application's rendered CV and cover-letter
  files (PDF/DOCX).

The button is on the Applications page; the browser downloads the zip directly.

## Jev cross-checking (optional)

TruthCV can optionally cross-check its own screening decisions against Jev
(TypeSafe System One), a third-party verification API, and — for
[Gmail response tracking](#gmail-response-tracking-optional) — use it as the
classifier itself rather than a secondary check. It's opt-in; nothing in the
app requires it.

Connect it from **Settings → Jev**, which saves the key into the same
encrypted secret store as your other credentials. There's no `.env` variable
for it in `.env.example` by design; if you'd rather not put the key through
the UI, set the `JEV_API_KEY` environment variable instead — it's consulted
as a fallback wherever the app would otherwise read the saved key. The env
var supplies only the key: the toggles below live in the settings store, so
you still enable them from **Settings → Jev**.

Two independent toggles control where Jev is consulted:

- **useForScreening** — cross-checks a posting's hard requirements (role
  type, salary floor, employment country, EOR, remote model) against Jev
  before rejecting or passing it during screening.
- **useForEmailTracking** — required before Gmail can be connected at all;
  with it off, `jev.confirm` fails open to `False` for every employer-reply
  classification, so each synced message is left an unclassified pending
  suggestion instead of being classified or auto-applied; see
  [Gmail response tracking](#gmail-response-tracking-optional) below.

A Jev answer is only treated as a confirmation at or above a confidence
(Noul) score of **0.8**; anything lower is treated as inconclusive. Jev
cross-checking is deliberately **fail-open**: if the key is missing, Jev is
unreachable, times out, or returns something unexpected, TruthCV proceeds
without it rather than blocking on it — Jev can only make screening more
cautious or gate an auto-apply, never make the app fail outright over a bare
transport error.

## Gmail response tracking (optional)

Connect Gmail from **Settings → Gmail** to have TruthCV watch your inbox for
employer replies to every application that isn't already **Interviewing**,
**Offer**, or **Rejected**, and suggest — or, when classified, apply — a
status update. A sync runs at most once every 5 minutes.

Each sync issues one scoped query per application, built from that
application's website/application-URL domains plus the first word of the
company name, OR'd with a quoted full-text search on the company name
itself, so it only fetches messages that look related to an application
you're tracking (a broad company name can still match some unrelated
senders) even when an application has no usable domain to search on.

Classification is done entirely by [Jev](#jev-cross-checking-optional) —
there's no LLM call involved. Each match is put to Jev as two yes/no
questions in turn, asking whether the email is a rejection and then whether
it's an interview invite; the first one Jev confirms wins the
classification. Only a **rejection** or **interview** classification
auto-applies anything, moving the application's status to **Rejected** or
**Interviewing** respectively and appending an evidence note (message id,
sender, subject, date) to its notes. Everything else — Jev confirms neither
question — is classified unrelated and left as a pending suggestion for you
to review and apply by hand; nothing is auto-applied without a Jev
confirmation.

Connecting Gmail itself requires a saved Jev key with **useForEmailTracking**
enabled — the connect button is blocked until that's set, since a Gmail
connection is only useful here for auto-applying Jev-confirmed transitions.

### Setting it up in Google Cloud Console

1. Create (or pick) a project in the [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the **Gmail API** for that project.
3. Configure the **OAuth consent screen**, adding the
   `https://www.googleapis.com/auth/gmail.readonly` scope — the only scope
   TruthCV requests; it can only read your mail, never send or modify it.
4. Create an OAuth client of type **Web application**, with an authorized
   redirect URI of `http://localhost:<APP_PORT>/api/auth/gmail/callback`
   (substitute your actual `APP_PORT`; TruthCV derives this same URI from the
   request host at runtime, so it must match exactly).
5. Set `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` in `.env` to
   the client's id and secret.
6. If the app is served behind a reverse proxy, or reached at anything other
   than `localhost:<APP_PORT>`, set `GOOGLE_OAUTH_REDIRECT_URI` in `.env` to
   the exact redirect URI registered above — request-derived detection can't
   be trusted through a proxy uvicorn doesn't trust, and the value must match
   the Google console entry character-for-character.
7. Connect from **Settings → Gmail** in the app.

## Unattended application agent

TruthCV also runs the applications, not just the paperwork. The agent
(`agent/`) is a headless run of TruthCV's own provider-neutral harness
(`agent/harness`), driven over MCP, that works through a target list,
screens each posting against your filters, generates the CV and cover letter
through the same guardrailed engine the wizard uses, submits the form, and
writes the result back into the ledger.

The agent holds no provider credential of its own: when `AGENT_API_TOKEN` is
set, it fetches the routed LLM credentials from the app at run start over a
guarded endpoint, using the independent Application agent route (or its Claude fallback), not simply whichever account was connected last.

Job boards, target companies and search profiles are configured on the
**Agents page** (`companyboards/`, `agentconfig/`), not in a file you edit by
hand.

It is a **separate container from the wizard, and the browser is a third**, so
a browser crash can never take either of them down. All three start together
(the launcher runs this for you):

```bash
docker compose up -d --build      # app, browser, agent
```

Schedule is configured on the Agents page (default **09:00 and 15:00** weekdays); `RUN_AT`/`RUN_DAYS` are fallback only, used when the agent config API is unreachable. Every
capability it has goes through TruthCV's MCP tool surface — it deliberately
does not mount the data volume.

> **It submits from a real Chromium**, running headful in its own `browser`
> container, not this one. Do the one-time manual login an ATS needs (SSO,
> CAPTCHA, SMS MFA) from the **Agents page → Site sign-ins**, which opens the
> browser's viewport in the app. That login persists on the `browser-profile`
> volume, so it survives restarts and later runs reuse it. The viewport is
> for signing in only — you cannot watch a run in progress, because a run and
> a sign-in session cannot hold the browser at the same time and the run
> wins. To see what a run did, read its log and the application ledger.
> There is no headless fallback:
> that was a deliberate choice, because a fresh, logged-out browser would
> apply as nobody. If the `browser` service is not reachable, the agent aborts
> the run rather than proceeding blind.

Configuration, the schedule, the browser precondition and the smoke test are
documented in [`agent/README.md`](agent/README.md). [`agent/targets.example.md`](agent/targets.example.md) is a tracked example of the operator's research scratchpad and is never read by the agent; the operative queue is `targetCompanies`, `companyBoards`, and `profiles` in the agent config, edited from the Agents page. What has actually been applied to, screened out or put in cooldown lives in the ledger and screening store on the data volume, not in that file.

### The plain-text application log

The ledger is the system of record, but a readable account is kept outside the
application as well, at `data/log/APPLICATION_LOG.md`:

```bash
python scripts/render_application_log.py
```

It renders every application in the ledger and **refuses to write at all** if
the rendered text does not account for each one exactly once — a log that
silently omits an application is worse than no log, because it reads as
complete. It is written one directory below the data volume root on purpose:
`GET /api/download/{name}` serves that root by bare filename without
authentication, and the log carries the same personal data the records do.

## Running it by hand

The launcher is the recommended path; this is the manual/advanced equivalent,
for anyone who wants to run compose directly.

```bash
# 1. Create your config from the template
cp .env.example .env

# 2. Set ENCRYPTION_KEY and AGENT_API_TOKEN (both required, both non-empty —
#    an empty AGENT_API_TOKEN aborts every scheduled run with
#    "session server unreachable at browser:8932"). Generate each with:
openssl rand -hex 32
# or, dependency-free:
python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

# 3. Build and run
docker compose up -d --build
```

This is exactly what the launcher automates: it runs the same `.env`
preparation via `python -m launcher`, which you can also invoke directly
without the per-OS scripts —

```bash
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/work" -w /work \
  python:3-alpine python -m launcher --repo /work
```

5627 is only the default — the actual URL depends on `APP_PORT` in your
`.env`. The app now prints its real URL at startup, so `docker compose logs
app` (or `docker compose ps`, whose PORTS column shows
`0.0.0.0:<host>->8080/tcp`) is the reliable way to find it. The app binds to
loopback only (`docker-compose.yml` maps `127.0.0.1:<host>->8080`), so it's
never reachable from another machine on your network.

Generated CVs and your truth file are persisted in `./data` (mounted into the
container), so they survive restarts.

**Before the agent applies to anything, seed your identity.** TruthCV ships
with no built-in identity — every ATS screening answer (name, email, phone,
work authorisation, ...) defaults to an empty string, and
the [unattended application agent](#unattended-application-agent) refuses to
submit while those fields are blank (`agent/RUNBOOK.md` §5). The normal route
is the web UI's **Settings** modal (`PUT /api/profile/answers`). Alternatively,
copy the tracked template, fill in your own details, then write them into the
data volume from inside a container — the volume is root-owned, so running
this directly on the host fails with a `PermissionError`:

```bash
cp answers.example.yaml answers.local.yaml
$EDITOR answers.local.yaml
docker compose run --rm -v "$(pwd)/answers.local.yaml:/app/answers.local.yaml" app \
  python -m truth.answers --answers /app/answers.local.yaml
```

Until one route or the other has run, the agent has no identity to submit
with.

### Upgrading

This version needs two things an older setup may not have:

- **A non-empty `AGENT_API_TOKEN` in `.env`** (`openssl rand -hex 32`). The
  browser container's session control server rejects an empty token, so every
  scheduled run aborts with `session server unreachable at browser:8932 - ...
  rejected the agent's X-Agent-Token`.
- **`docker compose up --build`, not `up`.** The `browser` image gains a
  session control server; an old image does not answer on port 8932, and every
  scheduled run aborts with the same message naming an unreachable server.

### Run fully offline with Ollama

No cloud API key required — TruthCV talks to a local Ollama container instead.
Connect **Ollama** in **Model routing → Accounts** and choose it as the Default model (or set `LLM_PROVIDER=ollama` in
`.env` as a fallback), then:

```bash
docker compose --profile ollama up --build

# First run only — pull a model into the ollama container:
docker compose exec ollama ollama pull llama3.1
```

## Configuration

All settings live in `.env` (copied from [`.env.example`](.env.example)). Most
of these are fallback defaults — routing choices select providers; saved
credentials take precedence over environment credentials for the chosen provider.

| Variable | What it does |
|---|---|
| `APP_PORT` | Host port the app is published on (default `5627`); the launcher advances this automatically if it's taken. |
| `ENCRYPTION_KEY` | Required — encrypts saved provider credentials at rest (`./data/secrets.enc`). The launcher generates it for you. |
| `AGENT_API_TOKEN` | Required, non-empty — shared secret the agent, app and browser containers authenticate to each other with. The launcher generates it for you. |
| `DATA_DIR` | Host path for persisted data (default `./data`). |
| `LLM_PROVIDER` | `anthropic` \| `openai` \| `ollama` — provider fallback when neither a default/task route nor a migrated provider choice is saved; connecting an account alone does not override it. |
| `LLM_MODEL` | Optional model id fallback after saved routes and any migrated model choice; blank uses the provider's default. Set a route on Model routing to override it. |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Fallback credential for the selected provider when its saved credential is unavailable. |
| `OLLAMA_HOST` | Ollama endpoint (compose sets this automatically). |
| `RUN_AT` / `RUN_DAYS` | Fallback agent schedule, used only when the Agents page's schedule is unreachable. |
| `TZ` | Fallback timezone the agent's schedule and logs are interpreted in (default `UTC`). The Agents page's schedule timezone takes precedence. |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Optional — Google OAuth client credentials backing the Gmail connection. See [Gmail response tracking](#gmail-response-tracking-optional) above for full setup steps. Unset, connecting Gmail reports "Google OAuth is not configured on the server." |
| `GOOGLE_OAUTH_REDIRECT_URI` | Optional — overrides the request-derived Gmail OAuth redirect URI. Needed behind a reverse proxy or when the app is reached at a non-localhost hostname; must match the Google console's registered redirect URI character-for-character. |
| `JEV_API_KEY` | Optional — fallback credential for [Jev cross-checking](#jev-cross-checking-optional), consulted only when no key is saved via Settings → Jev. Not present in `.env.example` by design. Supplies the key only — the use-for toggles are still set from Settings → Jev. |
| `DIAGNOSTICS_MCP_TOKEN` | Optional — bearer token guarding the read-only `/mcp/diagnostics` endpoint. Unset/empty (the default) disables the endpoint entirely: every request to it returns 404. See "Diagnostics MCP (read-only)" below. |

Generate `ENCRYPTION_KEY` or `AGENT_API_TOKEN` with either of the following:

```bash
openssl rand -hex 32
```

```bash
# No dependencies — works with any Python 3 install, before you build anything:
python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

### Operator vocabulary (`data/vocabulary/`)

Four optional plain-text files under `data/vocabulary/` (inside your `DATA_DIR`)
let an operator extend the pipeline's built-in word lists without a code change.
In every file, a line whose first character is `#` is a comment and is skipped,
as are blank lines. Any file that is missing means the built-in values are used
on their own — its absence is never an error.

| File | What it does |
|---|---|
| `arrangement_words.txt` | Extra work-arrangement "junk" words (e.g. remote/hybrid/onsite markers), one word per line, merged with a built-in set to filter non-skill keywords out of ATS keyword extraction. |
| `seniority_prefixes.txt` | Extra job-title seniority prefixes (e.g. `Senior`, `Lead`), one per line, merged with a built-in ladder to filter bare job titles out of extracted keywords. |
| `ats_headings.txt` | Extra standard CV section headings recognized by the ATS lint, one per line. |
| `synonyms.txt` | Acronym/expansion equivalence groups, one group per line, with the interchangeable forms separated by `=`. |

An example `synonyms.txt` line:

```
CI/CD = Continuous Integration and Continuous Delivery
```

> **`synonyms.txt` is trusted by the guardrail as truth.** Entries here are
> treated as truth-equivalent: if a candidate's truth data attests one form
> (say the acronym), the guardrail will also accept the other form (the
> expansion) as truthful in a rendered CV. Because of that, add only genuine
> equivalences — never loose or approximate synonyms. A false equivalence here
> would let an unattested claim pass the guardrail.

### Diagnostics MCP (read-only)

`/mcp/diagnostics` is a second, separate MCP streamable-HTTP JSON-RPC endpoint
on the `app` service, for a remote MCP client (Claude Desktop, an inspector,
your own tooling) to inspect a running TruthCV without touching the
operational `/mcp` surface the agent uses. It exposes exactly seven read-only
tools — `list_runs`, `get_run`, `list_screenings`, `list_applications`,
`get_status`, `get_gmail_sync_status`, `list_gmail_suggestions` — and none of
them can start a run, record a screening or application, or generate a
document. `get_status` reports per-store counts (including Gmail suggestion
count and last sync time) and whether secret encryption is available; it
never returns any secret material.

To enable it, set a non-empty `DIAGNOSTICS_MCP_TOKEN` in `.env` (e.g.
`openssl rand -hex 32`) and restart the `app` service. Every request must
carry it as a bearer token:

```
Authorization: Bearer <your DIAGNOSTICS_MCP_TOKEN>
```

A missing, wrong, or (while the token is unset) any Authorization header at
all gets a bare 404 — same convention as the agent's own token-guarded
routes — so the response never hints at whether the endpoint exists.

Register it in an MCP client as a streamable-HTTP server at
`http://<host>:<APP_PORT>/mcp/diagnostics` with that header attached; consult
your client's docs for where it wants custom headers configured.

> **Never publish the unauthenticated `/mcp` endpoint off-network.** `/mcp`
> (the operational surface the agent uses) carries no authentication at all —
> it relies entirely on being reachable only inside the Docker compose
> network. Exposing it (a port mapping, a reverse proxy, a tunnel) hands
> anyone who can reach it the ability to record applications, submit
> screenings and generate letters as you. If you need remote access, put a
> reverse proxy with its own auth in front, or use `/mcp/diagnostics` (which
> is at least bearer-token-guarded and strictly read-only) instead — and even
> then, prefer a private network or tunnel over a public port.

## Local development (without Docker)

Requires Python 3.11+ and Node 20+ (CI runs Python 3.12 / Node 22).

Backend:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set your provider + key, or connect one in Model routing
python -m api.main          # serves on http://localhost:8080
```

> Note: PDF/DOCX rendering shells out to system libraries that are **not** Python
> packages, so `pip install` does not provide them:
>
> - **WeasyPrint** native deps — cairo, pango, gdk-pixbuf, libffi.
> - **pandoc** — used for HTML→DOCX conversion.
> - A base font such as **DejaVu** — so generated PDFs render text correctly.
>
> The Docker image installs all of these for you (see the `Dockerfile`). For local
> dev, install them via your OS package manager, e.g. on Debian/Ubuntu:
>
> ```bash
> sudo apt-get install -y pandoc libpango-1.0-0 libpangocairo-1.0-0 \
>   libcairo2 libgdk-pixbuf-2.0-0 libffi-dev fonts-dejavu-core
> ```

Frontend (React + Vite + TypeScript, styled with MUI + Emotion — `npm install`
pulls these in):

```bash
cd web
npm install
npm run dev        # http://localhost:5173, proxies /api to the backend on :8080
```

Run the backend (above) alongside it. The Vite build outputs into `api/static`,
which the API serves in production.

## Tests

Backend:

```bash
pip install -r requirements-dev.txt
pytest
```

Frontend:

```bash
cd web && npm install && npm test
```

## How the guardrail works

The guardrail (`guardrail/`) is pure, deterministic, and uses **no LLM**. It
tokenizes each generated draft scope-by-scope and checks every token against the
allowed set derived from your truth file (plus stopwords). Anything untraceable
is grouped back under the exact bullet and section it came from, so you approve
or reject whole claims — the guardrail never mutates your truth file, and nothing
unapproved is rendered.
