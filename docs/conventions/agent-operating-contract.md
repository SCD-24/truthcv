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
- **Require integration tests for all primary API routing contracts**
- **Mock all outbound network requests and external API endpoints**
- **Add a regression test for every bug fix before it is merged**
- **Keep tests deterministic - no reliance on real time, randomness, or live network**

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

## Per-language rules (hand-written)

The projected global rules above are phrased for a single-language project. This
repository is not one: the backend and its tests are Python, while `web/` and
`agent/` are TypeScript/JavaScript. Where this section and a projected rule
disagree, **follow this section** - it describes the toolchain that actually
exists in the repo.

### Test frameworks

The projected rule `Jest for Frontend, Vitest for Backend Node` is wrong twice:
there is no Jest anywhere in this repository, and the backend is Python, not
Node. The real mapping is:

| Surface | Runner | Tests live in | Command |
|---|---|---|---|
| Python backend | pytest | `tests/` | `pytest -q` from the repo root |
| Web UI | Vitest | `web/src/**/*.test.tsx` | `npm test` in `web/` |
| Application Agent | Vitest | `agent/__tests__/` | `npm test` in `agent/` |

Configuration lives in `pyproject.toml` (`[tool.pytest.ini_options]`,
`testpaths = ["tests"]`), `web/vite.config.ts`, and `agent/vitest.config.ts`.

Write tests in the runner that owns the file you changed: never a JS test for
Python code, and never a Python test for `web/` or `agent/` code.

`.github/workflows/ci.yml` gates `pytest -q` and `web`'s `npm test`. The
`agent/` Vitest suite is **not** in CI, so run it locally whenever you touch
`agent/`.

### File and function length limits

The 400-line file limit and the 25-line function limit apply to **both** Python
and TS/JS, with two qualifications:

- **They do not apply to test files.** `tests/test_agent_mcp.py` (1330 lines)
  and several other suites exceed 400 lines by design. Do not split a test file
  to satisfy the rule.
- **They bind new files and deliberate rewrites.** `api/routes.py` (2308 lines)
  and `api/schemas.py` (1484 lines) are long for historical reasons; an
  incidental edit in one of them is not an invitation to refactor it. Propose a
  split as its own piece of work.

### Formatting and naming

`Prettier + ESLint (fix on save)` covers `web/` and `agent/` only. No Python
formatter (black, ruff) is configured, so in Python match the surrounding
file's style rather than reformatting it.

`camelCase for JS, PascalCase for classes` is the JS/TS convention. Python
follows PEP 8: `snake_case` for functions, variables and modules, `PascalCase`
for classes.

<!-- generated:start cap:canonical-names -->
## Canonical Names

Use these exact names and ids when discussing the architecture.

| Name | Id | Type |
|---|---|---|
| Agent Config | `agent-config` | backend |
| API | `api` | backend |
| Application Agent | `application-agent` | backend |
| Application Tracker | `application-tracker` | backend |
| Browser Service | `browser-service` | backend |
| Company Research | `company-research` | backend |
| Connections | `connections` | backend |
| Cover Letter Engine | `cover-letter-engine` | backend |
| Gmail / Google OAuth API | `gmail-api` | custom |
| Guardrail Validator | `guardrail-validator` | backend |
| Keyword Vocabulary | `keyword-vocabulary` | backend |
| LLM Provider Layer | `llm-provider-layer` | backend |
| LLM Provider Service | `llm-provider-service` | custom |
| Onboarding Store | `onboarding-store` | backend |
| Prompt Store | `prompt-store` | backend |
| Renderer | `renderer` | backend |
| Run Store | `run-store` | backend |
| Screening Engine | `screening-engine` | backend |
| Secret Store | `secret-store` | backend |
| Services Layer | `services-layer` | backend |
| Storage | `storage-leaf` | backend |
| Tailor Engine | `tailor-engine` | backend |
| Truth Data Volume | `truth-data-volume` | storage |
| Truth Store | `truth-store` | backend |
| Web UI | `web-ui` | frontend |
<!-- generated:end cap:canonical-names -->

<!-- generated:start cap:system-boundary -->
## System Boundary

The declared system consists of 25 component(s) and 88 connection(s) - see [the system map](../architecture/system-map.md). Anything not declared there is external to this system.
<!-- generated:end cap:system-boundary -->
