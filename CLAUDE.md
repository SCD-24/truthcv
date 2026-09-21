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
folded in here. Nothing live depends on that repository any more, but it is
retired rather than deleted — its working tree may still exist, and deleting it
is a user-gated step (see the audit) because it holds the only copy of some
gitignored personal data. Nor is every mention of it stale. Comments citing it
as the *origin* of ported code — for example the `BROWSER STRATEGY` block in [`agent/Dockerfile`](agent/Dockerfile),
the ported comments in `agent/*.sh`, `applications/log_render.py` and
`applications/model.py`, and the one-time importer
[`scripts/migrate_jobs_history.py`](scripts/migrate_jobs_history.py) — are
deliberate history and must be left alone. A verbatim archive of the
irreplaceable parts of the old tree (`applications/`, `scratchpad/` — the audit
lists what is deliberately *not* covered) sits on the data volume at
`data/migration/jobs-archive/`: outside git, root-owned, and reachable only from
inside a container mounting the volume. It keeps the old repository's original
absolute paths on purpose and must not be rewritten. [`docs/jobs-retirement-audit.md`](docs/jobs-retirement-audit.md)
records what was carried over. What *would* be stale is any live path, command
or instruction pointing into the old tree — there are currently none.

Two services, one image family:

- **`app`** — the wizard, the API, the guardrail, the ledger. Started by
  `docker compose up`.
- **`agent`** — the unattended application agent, started along with `app` on
  a bare `docker compose up` (only `ollama` still sits behind a compose
  profile). Schedule is configured on the Agents page (default 09:00/15:00
  weekdays; RUN_AT/RUN_DAYS are fallback only). Drives a containerised
  headful Chromium in the sibling `browser` service over HTTP MCP. There is
  no in-container browser and no headless fallback; see
  [`agent/README.md`](agent/README.md).
