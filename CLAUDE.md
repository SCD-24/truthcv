<!-- generated:start file:adapter:claude -->
# Aether Agent Workspace — Agent Entrypoint

Generated thin adapter. Canonical documentation lives in `docs/` — follow the links; never duplicate content here.

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

Two services, one image family:

- **`app`** — the wizard, the API, the guardrail, the ledger. Started by
  `docker compose up`.
- **`agent`** — the unattended application agent, on the `agent` compose
  profile so it is never started implicitly. Runs at 09:00 and 15:00 and drives
  the operator's real Chrome on the host through a bind-mounted interceptor
  socket. There is no in-container browser and no headless fallback; see
  [`agent/README.md`](agent/README.md).
