<!-- generated:start cap:contract-intro -->
> These architecture docs are **not verified at the current commit** (no full drift sweep has run yet). Treat them as a snapshot and verify against source before relying on them.

# Agent Operating Contract

Projected from the architecture canvas and global rules. Hand-written additions outside the generated blocks are preserved on regeneration.
<!-- generated:end cap:contract-intro -->

<!-- generated:start cap:trust-contract -->
## Documentation Trust Contract

> These architecture docs are **not verified at the current commit** (no full drift sweep has run yet). Treat them as a snapshot and verify against source before relying on them.

These docs are generated from the architecture canvas and verified against source by the drift detector. **Trust them as the architectural source of truth.** Do not read source merely to confirm what a doc already states.

Each architectural section carries one of three labels:

- **Verified** — checked clean at the current commit. Authoritative; do not re-verify against source.
- **Unhandled drift** — code and declared architecture diverge here. Reference only; verify against source.
- **Not verified** — the commit has moved since the last full sweep (or none ran). Treat as a snapshot; verify against source.

**Read source only when** the docs are incomplete or ambiguous, the section is **not** marked Verified, or you need exact implementation detail the docs do not guarantee (method signatures, variable names, algorithm specifics). When you do, read the minimum files needed.

**Self-check when detached from the IDE:** these labels reflect the last full drift sweep. If you are not in the Aether IDE, a Verified label holds only while the repo sits at the swept commit with a clean tree. `git status` confirms the tree is clean but cannot tell you the commit has advanced; if any commit has landed since the sweep, treat Verified sections as Not-verified snapshots and verify against source.

**Workflow:** (1) build understanding from the docs alone; (2) decide whether they suffice — if yes, proceed without opening source; (3) if not, name what is missing and open only the files that answer it.
<!-- generated:end cap:trust-contract -->

<!-- generated:start cap:global-rules -->
## Global Guidelines

# Global Guidelines & Standards

Define general standards, style guides, and testing rules for your AI agents to follow across the entire project codebase.

## Coding Standards
- **Functions should aim to be less than** `25` lines
- **Enforce code naming conventions:** `camelCase for JS, PascalCase for classes`
- **Require clear docstrings explaining the 'why' rather than 'what' for all public APIs**
- **Avoid deep nesting of code; limit to maximum** `3` levels

## Testing & Validation
- **Target a minimum unit test coverage of** `80` %
- **Primary testing framework to use:** `Jest for Frontend, Vitest for Backend Node`
- **Require integration tests for all primary API routing contracts**
- **Mock all outbound network requests and external API endpoints**

## AI Agent Execution Rules
- **Before writing code, explain your implementation plan first**
- **Preserve all existing comment blocks and license headers**
<!-- generated:end cap:global-rules -->

<!-- generated:start cap:canonical-names -->
## Canonical Names

Use these exact names and ids when discussing the architecture.

| Name | Id | Type |
|---|---|---|
| API | `api` | backend |
| Application Tracker | `application-tracker` | backend |
| Cover Letter Engine | `cover-letter-engine` | backend |
| Guardrail Validator | `guardrail-validator` | backend |
| LLM Provider Layer | `llm-provider-layer` | backend |
| LLM Provider Service | `llm-provider-service` | custom |
| Prompt Store | `prompt-store` | backend |
| Renderer | `renderer` | backend |
| Secret Store | `secret-store` | backend |
| Tailor Engine | `tailor-engine` | backend |
| Truth Data Volume | `truth-data-volume` | storage |
| Truth Store | `truth-store` | backend |
| Web UI | `web-ui` | frontend |
<!-- generated:end cap:canonical-names -->

<!-- generated:start cap:system-boundary -->
## System Boundary

The declared system consists of 13 component(s) and 26 connection(s) — see [the system map](../architecture/system-map.md). Anything not declared there is external to this system.
<!-- generated:end cap:system-boundary -->
