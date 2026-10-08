<!-- generated:start file:adapter:Codex -->
# Aether Agent Workspace — Agent Entrypoint

Generated thin adapter. Canonical documentation lives in `docs/` — follow the links; never duplicate content here.

- Operating contract: [docs/conventions/agent-operating-contract.md](docs/conventions/agent-operating-contract.md)
- System map: [docs/architecture/system-map.md](docs/architecture/system-map.md)
- Architecture overview: [docs/architecture/overview.md](docs/architecture/overview.md)
- Maturity & capabilities: [docs/system-level.yml](docs/system-level.yml)
<!-- generated:end file:adapter:Codex -->

## Repository scope

This is a single repository covering the whole system. It was previously split
in two — TruthCV generated the documents, a separate `Jobs` repo ran the
applications — and that second repo has been retired and its capabilities
folded in here. A live path, command or instruction pointing into a `Jobs`
repository is stale. Comments citing it as the origin of ported code (in
`agent/Dockerfile`, `agent/*.sh`, `applications/log_render.py`,
`applications/model.py` and `scripts/migrate_jobs_history.py`) are deliberate
history, not stale; see `CLAUDE.md` "Repository scope". The only place that repository is described is
[`docs/jobs-retirement-audit.md`](docs/jobs-retirement-audit.md), which records
what was carried over.

Three services start on a bare `docker compose up` — `app`, `browser` and
`agent`; only `ollama` sits behind a compose profile. Each builds from its
own Dockerfile (`Dockerfile`, `browser/Dockerfile`, `agent/Dockerfile`):

- **`app`** — the wizard, the API, the guardrail, the ledger. Started by
  `docker compose up`.
- **`browser`** — a containerised headful Chromium served by
  `@playwright/mcp`, reached by the agent over in-network HTTP MCP; see
  [`browser/README.md`](browser/README.md).
- **`agent`** — the unattended application agent, started along with `app` on
  a bare `docker compose up` (only `ollama` still sits behind a compose
  profile). Schedule is configured on the Agents page (default 09:00/15:00
  weekdays; RUN_AT/RUN_DAYS are fallback only). Drives a containerised
  headful Chromium in the sibling `browser` service over HTTP MCP. There is
  no in-container browser and no headless fallback; see
  [`agent/README.md`](agent/README.md).
