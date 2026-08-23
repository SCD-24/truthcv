# TruthCV
For the friends I made along the way.

Tailor your CV and cover letter to a job posting — **without inventing anything**.

TruthCV extracts a structured "truth file" from your LinkedIn PDF (every role,
date, bullet and skill tagged to its source), then tailors, reorders and rephrases
**only** facts that already exist. A deterministic guardrail diffs every generated
draft against the truth file: any claim it can't trace back to a real fact is
surfaced for your approval or blocked outright. Nothing unverified reaches the
output.

The flow is a browser wizard: **Upload LinkedIn PDF → Review extracted truth →
Paste job posting → Confirm inferences → Download PDF/DOCX** (plus an optional
guardrailed cover letter).

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

It is a **separate container from the wizard, and the browser is a third**, so
a browser crash can never take either of them down. All three start together:

```bash
docker compose up -d              # app, browser, agent
```

Schedule is configured on the Agents page (default **09:00 and 15:00** weekdays); `RUN_AT`/`RUN_DAYS` are fallback only, used when the agent config API is unreachable. Every
capability it has goes through TruthCV's MCP tool surface — it deliberately
does not mount the data volume.

> **It submits from a real Chromium**, running headful in its own `browser`
> container, not this one. Watch a run live, or do the one-time manual login
> an ATS needs (SSO, CAPTCHA, SMS MFA), at the noVNC viewport on
> http://localhost:7900 — that login then persists on the `browser-profile`
> volume, so it survives container restarts. There is no headless fallback:
> that was a deliberate choice, because a fresh, logged-out browser would
> apply as nobody. If the `browser` service is not reachable, the agent aborts
> the run rather than proceeding blind.

Configuration, the schedule, the browser precondition and the smoke test are
documented in [`agent/README.md`](agent/README.md). [`agent/targets.md`](agent/targets.md) is the operator's research scratchpad and is never read by the agent; the operative queue is `targetCompanies`, `companyBoards`, and `profiles` in the agent config. What has actually been applied to, screened out or put in cooldown lives in the ledger and screening store on the data volume, not in that file.

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

## Requirements

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose (recommended), **or** Python 3.11+ and Node 20+ for local dev.
- An LLM provider:
  - **Anthropic** or **OpenAI** — bring your own API key, or
  - **Ollama** — fully local/offline (no key needed), via the optional compose profile.

## Quick start (Docker)

```bash
# 1. Create your config from the template
cp .env.example .env

# 2. Edit .env — set LLM_PROVIDER and paste the matching API key
#    e.g. LLM_PROVIDER=anthropic  and  ANTHROPIC_API_KEY=sk-ant-...

# 3. Build and run
docker compose up --build
```

Then open **http://localhost:8080**.

Generated CVs and your truth file are persisted in `./data` (mounted into the
container), so they survive restarts.

**Before the agent applies to anything, seed your identity.** TruthCV ships
with no built-in identity — every ATS screening answer (name, email, phone,
work authorisation, ...) defaults to an empty string, and
the [unattended application agent](#unattended-application-agent) refuses to
submit while those fields are blank (`agent/RUNBOOK.md` §5). Copy the tracked
template, fill in your own details, then write them into the data volume from
inside a container — the volume is root-owned, so running this directly on
the host fails with a `PermissionError`:

```bash
cp answers.example.yaml answers.local.yaml
$EDITOR answers.local.yaml
docker compose run --rm -v "$(pwd)/answers.local.yaml:/app/answers.local.yaml" app \
  python -m truth.answers --answers /app/answers.local.yaml
```

You can also fill these in later from the web UI's **Settings** modal (same
file, via `PUT /api/profile/answers`) — but until one route or the other has
run, the agent has no identity to submit with.

### Run fully offline with Ollama

No cloud API key required — TruthCV talks to a local Ollama container instead:

```bash
# In .env set:  LLM_PROVIDER=ollama
docker compose --profile ollama up --build

# First run only — pull a model into the ollama container:
docker compose exec ollama ollama pull llama3.1
```

## Configuration

All settings live in `.env` (copied from [`.env.example`](.env.example)):

| Variable | What it does |
|---|---|
| `LLM_PROVIDER` | `anthropic` \| `openai` \| `ollama` — can also be set in Settings → Default model |
| `LLM_MODEL` | Optional model id override; blank uses each provider's default — can also be set in Settings → Default model |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Credential for the selected provider; env vars remain as fallback |
| `OLLAMA_HOST` | Ollama endpoint (compose sets this automatically) |
| `ENCRYPTION_KEY` | Optional — unlocks the in-app Settings → Accounts modal (provider credentials saved encrypted at rest) |
| `DATA_DIR` | Host path for persisted data (default `./data`) |

Provider accounts can be configured in the in-app **Settings → Accounts** modal (if `ENCRYPTION_KEY` is set), and env-var credentials remain as fallback. You can leave API keys blank in `.env` and set them from the app instead — the app encrypts them into `./data/secrets.enc`.

Per-task model routing is available in **Settings → Task models**, where you can override the default provider and model for specific operations: truth extraction, keywords, tailoring, inference, and cover letter generation. Cleared tasks use the default model.

Generate a key with either of the following and copy the printed value into
`ENCRYPTION_KEY`:

```bash
# No dependencies — works with any Python 3 install, before you build anything:
python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

# Or, once the app's dependencies are installed (local dev, or after `docker compose up --build`):
python -m api.genkey
```

Saved keys are encrypted (Fernet) into `./data/secrets.enc`.

## Local development (without Docker)

Backend:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set your provider + key
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

```bash
pip install -r requirements-dev.txt
pytest
```

## How the guardrail works

The guardrail (`guardrail/`) is pure, deterministic, and uses **no LLM**. It
tokenizes each generated draft scope-by-scope and checks every token against the
allowed set derived from your truth file (plus stopwords). Anything untraceable
is grouped back under the exact bullet and section it came from, so you approve
or reject whole claims — the guardrail never mutates your truth file, and nothing
unapproved is rendered.
