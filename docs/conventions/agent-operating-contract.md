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
- **Keep individual source files under** `400` lines
- **Avoid magic numbers; extract them into named constants**
- **Refactor duplicated logic into shared functions (DRY)**
- **Auto-format code with:** `Prettier + ESLint (fix on save)`

## Testing & Validation
- **Target a minimum unit test coverage of** `80` %
- **Primary testing framework to use:** `Jest for Frontend, Vitest for Backend Node`
- **Require integration tests for primary API routing contracts, run in-process with external dependencies mocked**
- **Mock all outbound network requests and external API endpoints**
- **Add a regression test for every bug fix before it is merged**
- **Keep tests deterministic - no reliance on real time, randomness, or live network**
- **Keep tests fast and isolated - mock external boundaries, use fake timers, no real sleeps, subprocesses, or disk/git I/O in unit tests**

## AI Agent Rules
- **Before writing code, explain your implementation plan first**
- **Preserve all existing comment blocks and license headers**
- **Reference exact file paths and line numbers when discussing code**
- **Ask for clarification when requirements are ambiguous instead of guessing**
- **Never commit, push, or open pull requests unless explicitly asked**
- **Keep changes minimal and scoped to the request**

## Security & Secrets
- **Never hardcode secrets, API keys, tokens, or credentials in source**
- **Validate and sanitize all external and user-supplied input**
- **Use parameterized queries; never build SQL by string concatenation**
- **Never log secrets, tokens, or personally identifiable information**

## Version Control & Git
- **Keep the commit subject line under** `72` characters
- **Commit message convention:** `Conventional Commits (feat:, fix:, chore:)`
- **Keep pull requests focused on a single logical change**
- **Never force-push to shared or protected branches**

## Documentation
- **Update relevant documentation whenever behavior changes**
- **Keep the README's setup and run steps accurate and runnable**

## Performance & Efficiency
- **Avoid N+1 queries; batch or eager-load data access**
- **Keep the initial JavaScript bundle under** `250` KB
- **Paginate or virtualize large lists and result sets**

## Error Handling & Logging
- **Handle errors explicitly; never silently swallow exceptions**
- **Emit structured, level-appropriate logs (no stray console output)**

## Accessibility & UX
- **Use semantic HTML elements and add ARIA only where needed**
- **All interactive elements must be fully keyboard-operable**
- **Provide descriptive alt text for all meaningful images**
- **Minimum text contrast ratio:** `4.5:1 (WCAG AA)`
<!-- generated:end cap:global-rules -->

<!-- generated:start cap:canonical-names -->
## Canonical Names

Use these exact names and ids when discussing the architecture.

| Name | Id | Type |
|---|---|---|
| API | `api` | backend |
| Application Agent | `application-agent` | backend |
| Application Pipeline | `application-pipeline` | backend |
| Arbeitnow Job Board API | `arbeitnow-api` | custom |
| Browser Service | `browser-service` | backend |
| Document Generation | `document-generation` | backend |
| Gmail / Google OAuth API | `gmail-api` | custom |
| Guardrail Validator | `guardrail-validator` | backend |
| Integrations | `integrations` | backend |
| Jev (TypeSafe System One) API | `jev-api` | custom |
| LLM Provider Layer | `llm-provider-layer` | backend |
| LLM Provider Service | `llm-provider-service` | custom |
| Orchestration | `orchestration` | backend |
| Secret Store | `secret-store` | backend |
| Storage & Shared Leaves | `storage` | backend |
| Truth Data Volume | `truth-data-volume` | storage |
| Truth Store | `truth-store` | backend |
| Web UI | `web-ui` | frontend |
<!-- generated:end cap:canonical-names -->

<!-- generated:start cap:system-boundary -->
## System Boundary

The declared system consists of 18 component(s) and 36 connection(s) - see [the system map](../architecture/system-map.md). Anything not declared there is external to this system.
<!-- generated:end cap:system-boundary -->
