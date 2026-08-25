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
does not require you to bring your own API key. Connect one from **Settings →
Accounts** (or during onboarding, see below) — TruthCV supports four:

- **Claude (Anthropic)** — sign in with a Claude Pro/Max subscription (OAuth,
  no API key needed), or paste an Anthropic API key.
- **ChatGPT (OpenAI)** — an OpenAI API key.
- **OpenRouter** — an OpenRouter API key.
- **Ollama** — no credential; point it at a local (or remote) Ollama URL.

Connected credentials are encrypted at rest into `./data/secrets.enc`. The
`LLM_PROVIDER` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` variables in `.env`
are a **fallback only**, used when no connection has been made — whatever is
connected in the app always takes precedence.

Per-task model routing is available in **Settings → Task models**, where you
can override the default provider and model for specific operations: truth
extraction, keywords, tailoring, inference, and cover letter generation.
Cleared tasks use the default model.

### Onboarding

The first time you open TruthCV, a guided onboarding flow (rather than the
main app) greets you: it walks you through connecting a provider and
uploading/reviewing your CV, skipping any step you've already completed, then
hands off into a short guided tour of the app. You only see it until those
steps are satisfied.

## What's in the app

TruthCV is a multi-page app, not a single linear wizard:

- **Analytics** — the landing page, with side navigation to everything else.
- **Applications** — the job-application ledger (see below).
- **Screenings & Approvals** — screened postings awaiting your decision,
  including cover-letter approvals and cooldowns before an already-skipped
  company is reconsidered.
- **Company research** — background TruthCV has gathered on a company, with
  its source recorded alongside each fact.
- **Agents** — the unattended agent's run history, schedule, target companies
  and job boards, and site sign-ins.

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

## Unattended application agent

TruthCV also runs the applications, not just the paperwork. The agent
(`agent/`) is a headless Claude Code process that works through a target list,
screens each posting against your filters, generates the CV and cover letter
through the same guardrailed engine the wizard uses, submits the form, and
writes the result back into the ledger.

The agent holds no provider credential of its own: when `AGENT_API_TOKEN` is
set, it fetches the routed LLM credentials from the app at run start over a
guarded endpoint, so it always uses whatever provider you've connected.

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
Select **Ollama** in **Settings → Accounts** (or set `LLM_PROVIDER=ollama` in
`.env` as a fallback), then:

```bash
docker compose --profile ollama up --build

# First run only — pull a model into the ollama container:
docker compose exec ollama ollama pull llama3.1
```

## Configuration

All settings live in `.env` (copied from [`.env.example`](.env.example)). Most
of these are fallback defaults — the app-side connections above take
precedence once configured.

| Variable | What it does |
|---|---|
| `APP_PORT` | Host port the app is published on (default `5627`); the launcher advances this automatically if it's taken. |
| `ENCRYPTION_KEY` | Required — encrypts saved provider credentials at rest (`./data/secrets.enc`). The launcher generates it for you. |
| `AGENT_API_TOKEN` | Required, non-empty — shared secret the agent, app and browser containers authenticate to each other with. The launcher generates it for you. |
| `DATA_DIR` | Host path for persisted data (default `./data`). |
| `LLM_PROVIDER` | `anthropic` \| `openai` \| `ollama` — fallback only; overridden by whatever is connected in Settings → Accounts. |
| `LLM_MODEL` | Optional model id override; blank uses each provider's default — fallback only, also settable in Settings → Task models. |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Fallback credential for the selected provider, used only when nothing is connected in the app. |
| `OLLAMA_HOST` | Ollama endpoint (compose sets this automatically). |
| `RUN_AT` / `RUN_DAYS` | Fallback agent schedule, used only when the Agents page's schedule is unreachable. |
| `TZ` | Timezone the agent's schedule and logs are interpreted in (default `UTC`). |

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

## Local development (without Docker)

Requires Python 3.11+ and Node 20+ (CI runs Python 3.12 / Node 22).

Backend:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set your provider + key, or connect one in Settings
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
