# LLM Provider Connections — Design

Date: 2026-08-17
Status: awaiting review

Multi-account LLM provider connections configured under Settings, with
subscription (OAuth) and API-key auth modes, live model discovery, and
per-task + agent model routing. Modeled on the provider-connection design in
the Aether project (`/mnt/projects/code/aether`), re-implemented for
truthcv's Python/FastAPI + React stack.

## Goals

- Connect multiple LLM accounts side by side instead of today's single
  provider/key/model triple.
- Subscription auth: sign in with Claude Pro/Max, ChatGPT/Codex, GitHub
  Copilot, and Google (Antigravity/Gemini) consumer subscriptions, using each
  vendor's first-party CLI OAuth client.
- API-key auth: Anthropic, OpenAI, Google, OpenRouter keys; Ollama URL.
- Choose a `{connection, model}` per wizard task and for the unattended
  agent, with a global default.
- Existing users migrate automatically — no key re-entry (see Migration).

## Non-goals

- Capability tiers (fast/standard/deep) and per-sub-agent routing (aether has
  them; truthcv has no sub-agents).
- Multi-account-per-provider (one connection per provider card, each card
  optionally holding both an OAuth record and an API key, like aether).
- API authentication for the app in general (out of scope; one guarded
  endpoint is the exception, see Agent wiring).
- Background token-refresh jobs; refresh is lazy at call time.

## Known caveats (accepted)

- The four subscription flows reuse the vendors' CLI OAuth clients (Claude
  Code, Codex CLI, VS Code Copilot, Gemini CLI). These are undocumented and
  ToS-gray; aether's source carries the same caveat.
- Codex login requires host port 1455 free and published from the `app`
  container (fixed registered redirect URI).
- Anthropic subscription calls must send the literal Claude Code system
  preamble ("You are Claude Code, Anthropic's official CLI for Claude.") as
  the first system block, plus `anthropic-beta: oauth-2025-04-20`, and
  authenticate with `Authorization: Bearer` (no `x-api-key`).

## Provider catalog

| Card key | Vendor | Subscription (flow) | API key / URL |
|---|---|---|---|
| `claude` | Anthropic | PKCE paste-code (Claude Code client) | `sk-ant-…` |
| `codex` | OpenAI | Browser + loopback on port 1455 (Codex CLI client) | `sk-…` |
| `copilot` | GitHub | Device-code; two-tier token (GitHub token → ~25-min Copilot bearer + api base) | — |
| `antigravity` | Google | Browser + callback `/api/auth/antigravity/callback`; Code Assist project onboarding | `AIza…` (Gemini) |
| `openrouter` | OpenRouter | — | key |
| `ollama` | Local | — | base URL + optional bearer |

A card's two modes can speak different wire formats (e.g. Codex subscription
uses the Responses API; an OpenAI key uses chat-completions). The catalog is
a constant in both backend and frontend; model lists are never hardcoded —
always discovered live.

## Storage

### Credentials — `secretstore` v2 (encrypted)

Same Fernet-encrypted `data/secrets.enc`, new versioned schema replacing the
flat 5-field whitelist:

```jsonc
{
  "version": 2,
  "connections": {
    "claude":      { "oauth": { "accessToken", "refreshToken", "expiresAt", "scope", "connectedAt" },
                     "apiKey": "sk-ant-…", "authMode": "subscription" | "apikey" },
    "codex":       { "oauth": { "accessToken", "refreshToken", "idToken", "accountId", "email", "plan", "expiresAt", "connectedAt" },
                     "apiKey": "sk-…", "authMode": "…" },
    "copilot":     { "oauth": { "githubToken", "copilotToken", "copilotExpiresAt", "apiBase", "connectedAt" } },
    "antigravity": { "oauth": { "accessToken", "refreshToken", "email", "projectId", "expiresAt", "connectedAt" },
                     "apiKey": "AIza…", "authMode": "…" },
    "openrouter":  { "apiKey": "…" },
    "ollama":      { "baseUrl": "…", "bearer": "…" }
  }
}
```

Unknown keys inside a connection are preserved on rewrite (the v1
whitelist-drop behavior is removed). Tokens and keys never reach the
browser; status responses carry booleans and metadata only
(`subscriptionConnected`, `apiKeyConnected`, `email`, `plan`, `expiresAt`,
`connectedAt`). Same degrade behavior as today when `ENCRYPTION_KEY` is
missing: env-only, read-only.

### Routing — new `modelrouting/` package (not secret)

`data/model_routing.json`, dataclass store modeled on `agentconfig/store.py`
(defensive `from_dict`, atomic tmp+rename, path from `truth.store.data_dir()`):

```jsonc
{
  "tasks": {
    "truth_extract":  { "connection": "claude", "model": "…" } | null,
    "keywords":       …, "tailor": …, "infer": …, "cover_letter": …
  },
  "agent":   { "connection": "claude", "model": "…" } | null,
  "default": { "connection": "claude", "model": "…" } | null
}
```

Task ids are introduced here as a `TaskName` literal/enum — the first named
identity these call sites have. Both new packages are added to the
Dockerfile COPY list.

## Migration (hard requirement: no key re-entry)

- **v1 → v2 lift, automatic, lossless, idempotent.** On first load of a v1
  `secrets.enc`: `anthropicApiKey` → `connections.claude.apiKey`,
  `openaiApiKey` → `connections.codex.apiKey`, `ollamaHost` →
  `connections.ollama.baseUrl`; `activeProvider` + `model` seed
  `routing.default` (provider name mapped to card key: `anthropic`→`claude`,
  `openai`→`codex`, `ollama`→`ollama`). A `secrets.enc.v1.bak` copy is
  written before the rewrite. A v2 file is never re-migrated. Behavior is
  identical before anyone opens Settings.
- **Env fallback preserved.** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `OLLAMA_HOST`, `LLM_PROVIDER`, `LLM_MODEL` remain the layer under the
  store, merged as `resolve_credentials()` does today: stored connection
  wins, env fills gaps. Env-only users keep working with zero action.
- **Empty-key-keeps-existing** POST semantics carried forward, so the UI
  never forces re-entry.

## Backend

### Auth modules — `connections/auth/`

One module per vendor (`claude.py`, `codex.py`, `copilot.py`,
`antigravity.py`, `apikey.py`), ported 1:1 from aether's flows:

- Claude: PKCE paste-code (`code#state`), authorize `https://claude.ai/oauth/authorize`,
  token `https://console.anthropic.com/v1/oauth/token`, Claude Code client id.
- Codex: browser flow; the registered redirect is literally
  `http://localhost:1455/auth/callback`, so the app serves
  `GET /auth/callback` (outside the `/api` prefix) and compose additionally
  maps host port 1455 to the app container; form-encoded token exchange;
  account id/plan mined from the id_token.
- Copilot: device-code start returns `{userCode, verificationUri}`; server
  background-polls GitHub (honoring `slow_down`); lazy exchange of the
  durable GitHub token for the short-lived Copilot bearer + api base.
- Antigravity: browser flow to `/api/auth/antigravity/callback`,
  `access_type=offline&prompt=consent`, then Code Assist project
  discovery/onboarding (LRO polling), cached on the record.
- Refresh: lazy on use, 5-minute expiry skew, refresh responses that omit
  `refresh_token` keep the old one. One `asyncio.Lock` per connection so
  concurrent requests never double-refresh (closes aether's known gap).
- Pending OAuth state (PKCE verifier, `state`) lives in module memory,
  never persisted, never sent to the client.

### Routes (existing `api/routes.py` router, wire models in `api/schemas.py`)

| Route | Behavior |
|---|---|
| `GET /api/auth/{provider}/status` | Connection state, both modes side by side; never tokens. |
| `POST /api/auth/{provider}/start` | Returns `{flow: "paste-code"\|"browser"\|"device-code", authUrl?, userCode?, verificationUri?}`. |
| `POST /api/auth/claude/complete` | Exchange pasted `code#state`. |
| `GET /auth/callback` | Codex loopback redirect (host port 1455, outside the `/api` prefix — fixed registered URI). |
| `GET /api/auth/antigravity/callback` | Google redirect; verify `state`, exchange, onboard project in background. |
| `POST /api/auth/{provider}/key` | Validate by listing models with the key; 400 with human message on failure; store; return models. |
| `GET /api/auth/{provider}/models?mode=` | Live model list (`null` = unknown). |
| `POST /api/auth/{provider}/logout?mode=` | Clear OAuth record or key; cancel pending login; clear model cache. |
| `GET/PUT /api/routing` | Read/patch routing (partial-update convention via `exclude_unset`). |
| `GET /api/agent/llm-credentials` | Guarded; see Agent wiring. |

Existing `/api/settings` routes are reworked to read/write the v2 store
(status booleans per connection) — the old single-provider POST shape stays
accepted during a deprecation window and writes into the corresponding
connection.

### Providers — extend existing `providers/` ABC

- `anthropic_provider` gains OAuth mode: bearer auth, beta header, Claude
  Code preamble prepended as first system block.
- New: `codex_provider` (ChatGPT Responses API, SSE-only, httpx),
  `copilot_provider` (chat-completions against the exchanged `apiBase`, VS
  Code editor headers), `antigravity_provider` (Code Assist generateContent,
  `project` in body), `openrouter_provider` (OpenAI SDK with `base_url`).
- `get_provider()` becomes `get_provider(task: TaskName | None = None)`:
  routing lookup (task → default → env-derived v1 behavior) → connection →
  provider instance, cached per `(connection, model)`; `reset_provider()`
  clears the cache. Call sites that change: the `get_provider()` calls in
  `api/routes.py` and `mcp/tools_letter.py` gain their task name; the six
  task functions keep receiving an injected `LLMProvider`.

### Model discovery

Per connection+mode, in-memory cache TTL 10 min (Antigravity 6 h — its
discovery probes candidate models with 1-token calls). Model shape
`{id, name, contextWindow?, disabled?, disabledReason?}`; entitlement-blocked
Copilot models stay visible but disabled with a reason; `contextWindow`
normalized to an input cap; absent stays absent.

## Frontend

- **Settings modal** (`web/src/settings/SettingsModal.tsx`) gains two
  sections in the existing `SettingsSection` pattern:
  - **Accounts** — one card per catalog entry: status line, Subscription |
    API key toggle (dual-mode cards), Connect/Disconnect, and per-flow UI:
    paste-code textbox (Claude), open-browser + status polling (Codex,
    Antigravity), user-code + verification link display (Copilot), key/URL
    fields (apikey mode, Ollama).
  - **Task models** — five task rows + a Default row, each a connection
    select + model select fed by live model lists (with the existing
    `__custom__` free-text escape hatch).
  - The current single provider/key/model panel is replaced by these
    sections.
- **Agents page** (`web/src/agents/AgentsPage.tsx`) gains a **Model**
  section: connection + model for the unattended agent, stored in
  `routing.agent`. Only Anthropic-family connections are offered (the agent
  runs the Claude Code CLI).
- New client functions in `web/src/api/client.ts`, types in
  `web/src/api/types.ts`.

## Agent wiring

- New endpoint `GET /api/agent/llm-credentials`: returns a fresh access
  token (refreshing if needed) or API key for the connection routed to
  `agent`, plus the model id. Because the API is otherwise unauthenticated
  and this endpoint returns a live token, it requires a shared-secret header
  (`X-Agent-Token`), value from an env var both services receive in
  `docker-compose.yml`. Requests without the correct secret get 404.
- `agent/daily-apply.sh` fetches it at run start (via the existing
  `agent-config.js`-style HTTP channel): subscription → export
  `CLAUDE_CODE_OAUTH_TOKEN`; API key → export `ANTHROPIC_API_KEY`; either
  way pass `--model` to the `claude` invocation. On fetch failure or no
  routing, fall back to today's env `ANTHROPIC_API_KEY` and default model,
  and say so in the run log.
- `agent/README.md` and `.env.example` updated accordingly.

## Error handling

- OAuth failures surface as human-readable messages on the card (invalid
  pasted code, denied consent, port 1455 busy, device-code expiry).
- Refresh failure marks the connection `expired` in status; calls routed to
  it fail with a clear "reconnect <provider>" error rather than a raw 401.
- A routed connection that is disconnected falls back task → default; if
  nothing resolves, the task errors the way a missing key errors today.
- Key validation failure on POST returns 400 with the provider's message;
  nothing is stored.

## Testing

- pytest per new package: auth flows against mocked vendor endpoints
  (respx), refresh + skew + concurrent-refresh lock, secretstore v1→v2
  migration (including `.bak` and idempotency), routing resolution ladder,
  route handlers via `TestClient` with the `data_dir` fixture, provider
  request-shaping (OAuth headers, preamble, wire formats) against fakes.
- vitest colocated tests for the Accounts and Task-models sections and the
  Agents-page Model section.
- No live-vendor tests. Manual smoke checklist per subscription flow in the
  PR description.

## Build stages (each shippable)

1. **Foundations + Claude subscription + keys** — secretstore v2 +
   migration, catalog, apikey auth, Claude OAuth, routing store with
   default-only resolution, Accounts UI for those cards, reworked settings
   routes.
2. **Routing + agent** — task ids threaded through `get_provider`, Task
   models UI, Agents-page Model section, `llm-credentials` endpoint +
   `daily-apply.sh` wiring.
3. **Remaining vendors** — Codex, Copilot, Antigravity auth + providers +
   discovery; OpenRouter.

Stage order puts user-visible value (routing, agent on subscription) before
the long tail of vendors.
