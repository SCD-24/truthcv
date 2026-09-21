<!-- generated:start file:adapter:claude -->
# Aether Agent Workspace - Agent Entrypoint

Generated thin adapter. Canonical documentation lives in `docs/` - follow the links; never duplicate content here.

- Operating contract: [docs/conventions/agent-operating-contract.md](docs/conventions/agent-operating-contract.md)
- System map: [docs/architecture/system-map.md](docs/architecture/system-map.md)
- Architecture overview: [docs/architecture/overview.md](docs/architecture/overview.md)
- Maturity & capabilities: [docs/system-level.yml](docs/system-level.yml)
<!-- generated:end file:adapter:claude -->

## Repository scope

This is a single repository covering the whole system. It was previously split
in two — TruthCV generated the documents, a separate `Jobs` repo ran the
applications — and that second repo has been retired and its capabilities
folded in here. If you find a reference to a `Jobs` repository, or an absolute
path into one, it is stale; the only place that repository is described is
[`docs/jobs-retirement-audit.md`](docs/jobs-retirement-audit.md), which records
what was carried over.

Three services start on a bare `docker compose up` — `app`, `browser` and
`agent`; only `ollama` still sits behind a compose profile. They do not share
an image: each builds its own from a different base (root `Dockerfile` →
python:3.11-slim with a node:20-slim web build stage; `agent/Dockerfile` →
node:22-bookworm-slim; `browser/Dockerfile` →
mcr.microsoft.com/playwright:v1.49.0-noble). What they share is the compose
build context (`context: .`).

- **`app`** — the wizard, the API, the guardrail, the ledger. Started by
  `docker compose up`.
- **`browser`** — a containerised headful Chromium running under Xvfb and
  served by `@playwright/mcp`, reached by the agent over in-network HTTP MCP,
  with a persistent browser-profile volume; see
  [`browser/README.md`](browser/README.md).
- **`agent`** — the unattended application agent, started along with `app` on
  a bare `docker compose up`. Schedule is configured on the Agents page
  (default 09:00/15:00 weekdays; RUN_AT/RUN_DAYS are fallback only). Drives
  the headful Chromium in the sibling `browser` service over HTTP MCP. There
  is no in-container browser and no headless fallback; see
  [`agent/README.md`](agent/README.md).
