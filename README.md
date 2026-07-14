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
| `LLM_PROVIDER` | `anthropic` \| `openai` \| `ollama` |
| `LLM_MODEL` | Optional model id override; blank uses each provider's default |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Credential for the selected provider |
| `OLLAMA_HOST` | Ollama endpoint (compose sets this automatically) |
| `ENCRYPTION_KEY` | Optional — unlocks the in-app Settings modal (keys saved encrypted at rest) |
| `DATA_DIR` | Host path for persisted data (default `./data`) |

You can leave the API key blank in `.env` and instead enter/save it from the
in-app **Settings** modal — but that feature only turns on if `ENCRYPTION_KEY`
is set.

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
