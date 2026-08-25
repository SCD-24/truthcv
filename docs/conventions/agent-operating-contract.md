<!-- generated:start cap:contract-intro -->
# Agent Operating Contract

Projected from the architecture canvas and global rules. Hand-written additions outside the generated blocks are preserved on regeneration.

These docs describe the intended architecture and are authoritative; read source only for implementation detail they do not specify.
<!-- generated:end cap:contract-intro -->


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
| Agent Config | `agent-config` | backend |
| API | `api` | backend |
| Application Agent | `application-agent` | backend |
| Application Tracker | `application-tracker` | backend |
| Company Research | `company-research` | backend |
| Connections | `connections` | backend |
| Cover Letter Engine | `cover-letter-engine` | backend |
| Gmail / Google OAuth API | `gmail-api` | custom |
| Guardrail Validator | `guardrail-validator` | backend |
| LLM Provider Layer | `llm-provider-layer` | backend |
| LLM Provider Service | `llm-provider-service` | custom |
| Onboarding Store | `onboarding-store` | backend |
| Prompt Store | `prompt-store` | backend |
| Renderer | `renderer` | backend |
| Run Store | `run-store` | backend |
| Screening Engine | `screening-engine` | backend |
| Secret Store | `secret-store` | backend |
| Tailor Engine | `tailor-engine` | backend |
| Truth Data Volume | `truth-data-volume` | storage |
| Truth Store | `truth-store` | backend |
| Web UI | `web-ui` | frontend |
<!-- generated:end cap:canonical-names -->

<!-- generated:start cap:system-boundary -->
## System Boundary

The declared system consists of 21 component(s) and 50 connection(s) — see [the system map](../architecture/system-map.md). Anything not declared there is external to this system.
<!-- generated:end cap:system-boundary -->
