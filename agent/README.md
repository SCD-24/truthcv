# The unattended application agent

A second container alongside TruthCV's `app` service. On a schedule it runs a
provider-neutral agent harness against [`RUNBOOK.md`](RUNBOOK.md), finds roles,
applies to them in a real browser, and records what it did through TruthCV's own
tools.

It is deliberately a separate service and a separate image: a browser session
going wrong must never take the wizard down with it, and the wizard's image
stays free of agent tooling.

## The browser is in its own container, not this one.

**This image contains no browser.** No Chrome, no Chromium, no Xvfb, no
Playwright — and re-adding one is not a fix.

The agent drives a headful Chromium reached over in-network HTTP MCP at
`BROWSER_MCP_URL` (default `http://browser:8931/mcp`, see
[`mcp.json`](mcp.json)). That browser runs under Xvfb in its own Compose
service, `browser`, built from `browser/Dockerfile` — see
[`browser/README.md`](../browser/README.md) for how that container works.
Keeping it in a sibling container rather than this one means a browser crash
can never take the agent's own run loop down.

> **A login-walled site (SSO, CAPTCHA, SMS MFA) needs a one-time manual
> sign-in.** Open **Agents → Site sign-ins** in TruthCV and click Sign in; a
> browser you can drive opens in the app. The session persists on the named
> volume `browser-profile`, so you should not need to sign in again. A run in
> progress takes priority — the button is refused while the agent is applying,
> and a run that starts during a session asks for the browser back with three
> minutes' notice. See [`browser/README.md`](../browser/README.md) for detail.

## The agent has no identity until you seed one

`get_profile_answers` returns every field — name, email, phone, work
authorisation, and the rest — as `""` on a fresh install. `truth/answers.py`
ships with no personal defaults on purpose. Seed your own before the first
run:

```bash
cp answers.example.yaml answers.local.yaml
$EDITOR answers.local.yaml
docker compose run --rm -v "$(pwd)/answers.local.yaml:/app/answers.local.yaml" app \
  python -m truth.answers --answers /app/answers.local.yaml
```

The data volume is root-owned, so that has to run inside a container, not
directly on the host — `python -m truth.answers` run on the host fails with
`PermissionError`. You can also fill these in from the web UI's Settings
modal instead of the file.

**Unseeded, the agent will not submit.** `RUNBOOK.md` §5 stops before applying
if the required fields — name, email, work authorisation — come back blank,
and reports it as an open issue rather than filing a blank application.

## Running it

The agent and its `browser` both start on a bare `docker compose up` — they are
no longer behind a compose profile. The agent waits for the browser to report
healthy before its first run:

```bash
export ANTHROPIC_API_KEY=...           # never commit this
docker compose up -d                            # app, browser, agent
docker compose logs -f agent
```

Starting the scheduled loop on its own also brings the browser up, because the
agent depends on it:

```bash
docker compose up -d agent
```

Check the schedule without waiting for it — this starts nothing and applies to
nothing:

```bash
docker compose run --rm \
  --entrypoint /app/agent/entrypoint.sh agent --check-schedule
```

Run the smoke test — also submits nothing (see [Verification](#verification)):

```bash
docker compose run --rm \
  --entrypoint /app/agent/smoke-test.sh agent
```

One immediate run:

```bash
docker compose run --rm -e RUN_ONCE=1 agent
```

**`RUN_ONCE=1` is a live test, not a dry run.** It submits real applications
under the operator's name. Watch it.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Injected at runtime, never baked into the image. Checked at container start. **Fallback only** when `AGENT_API_TOKEN` is unset; when it is set, credentials are fetched from `GET /api/agent/llm-credentials` at run start. |
| `AGENT_API_TOKEN` | unset | Shared secret (generate with `openssl rand -hex 32`). When set, the agent fetches LLM credentials from the app at run start via a guarded endpoint; when unset, it uses `ANTHROPIC_API_KEY` directly (original behavior). |
| `RUN_AT` | `09:00,15:00` | Comma-separated `HH:MM` (24h, container TZ). Fallback only — used when the agent config API is unreachable; see below. |
| `RUN_DAYS` | `1,2,3,4,5` | Days to run, `1`=Mon … `7`=Sun. Fallback only — used when the agent config API is unreachable; see below. |
| `RUN_ONCE` | unset | `1` = run immediately and exit. |
| `TZ` | container default | Timezone the schedule is expressed in. |
| `TRUTHCV_MCP_URL` | `http://app:8080/mcp` | The `app` service's MCP streamable-HTTP JSON-RPC tool surface (`POST /mcp`, `agenttools/mcp_app.py`). In-network only — not reachable from the host or the internet. |
| `AGENT_BROWSER_DRIVER` | `browser` | Which browser driver the agent uses. `browser` (the containerised Chromium) is currently the only supported value — kept as a validating seam so a second driver can be added later without every call site needing to change. |
| `BROWSER_MCP_URL` | `http://browser:8931/mcp` | In-network address of the `browser` compose service's MCP endpoint (see [`browser/README.md`](../browser/README.md)). Also in-network only. Used by the `browser` driver. |
| `MAX_APPLICATIONS_PER_RUN` | empty | Fallback only: `maxApplicationsPerRun` on the Agents page takes precedence. Empty in both means **no cap**, matching RUNBOOK §1 ("there is no daily quota"). Not zero. Enforced server-side on the approved-queue path (`get_approved_applications` caps and leases what it hands out); on a posting the agent discovers itself in FULL AUTO it is prompt-level only. |
| `RUN_LOG_DIR` | `/app/runs` | Where `daily-apply.sh` writes per-run logs. Must stay inside the `agent-runs` volume or logs vanish on restart. |

The agent runs a provider-neutral harness (`agent/harness`, compiled into the image), so the **Model** setting on the Agents page can point at any supported provider — `claude`, `codex`, `openrouter`, or `ollama` — chosen via the connection configured in Settings. The harness's credentials are resolved at run start through `GET /api/agent/llm-credentials`.

### Harness configuration surface

`daily-apply.sh` invokes the harness as `node "$HARNESS_CLI"` and hands it the
provider, wire, model, credential, and auth type it resolved from the app (or,
absent `AGENT_API_TOKEN`, straight from the container's own environment). The
knobs below are that whole surface.

**Providers and wires.** The harness targets four logical **providers** —
`claude`, `codex`, `openrouter`, `ollama` — over one of two **wires**:
`anthropic-messages` or `openai-chat-completions`. `claude` speaks the
`anthropic-messages` wire; `codex`, `openrouter`, and `ollama` speak the
`openai-chat-completions` wire. On the OpenAI wire, when no base URL is supplied,
the harness fills in a per-provider default (`OPENAI_WIRE_DEFAULTS` in
`agent/harness/providers/registry.ts`):

| Provider | Default wire | Default base URL when none is given |
|---|---|---|
| `claude` | `anthropic-messages` | the Anthropic adapter's own default |
| `codex` | `openai-chat-completions` | `https://api.openai.com/v1` |
| `openrouter` | `openai-chat-completions` | `https://openrouter.ai/api/v1` |
| `ollama` | `openai-chat-completions` | none — you **must** supply a base URL |

**Auth routing.** `AGENT_LLM_AUTH_TYPE` is one of `oauth`, `api_key`, or `url`,
and it is distinct from the provider. It selects *how* the token is presented on
the wire: `oauth` sends it as a Bearer token, `api_key` as the vendor api-key
header (`x-api-key` on the Anthropic wire), and `url` carries no credential (as
with `ollama`, which reaches its endpoint by base URL alone). A `claude`
connection can be either `oauth` or `api_key`, so the two are kept apart: an
OAuth Claude credential sent as an api key is **rejected** by the provider, so
the auth type must match the credential's kind.

**Environment variables.** The harness reads these (each has an equivalent CLI
flag that takes precedence; `daily-apply.sh` passes the flags explicitly):

| Env var | Meaning |
|---|---|
| `AGENT_LLM_PROVIDER` | Logical provider: `claude`, `codex`, `openrouter`, or `ollama`. |
| `AGENT_LLM_WIRE` | Wire protocol: `anthropic-messages` or `openai-chat-completions`. |
| `AGENT_LLM_MODEL` | Model identifier requested from the provider. |
| `AGENT_LLM_API_KEY` | Credential token (api key or OAuth token). May be empty only for `ollama`. Never echoed — the harness redacts it from all output. |
| `AGENT_LLM_BASE_URL` | Base URL. Required for `ollama`; optional elsewhere (falls back to the per-provider default above). |
| `AGENT_LLM_AUTH_TYPE` | How to present the token: `oauth`, `api_key`, or `url`. |
| `AGENT_CONTEXT_WINDOW` | The model's **input** context capacity in tokens, digits only; values that are not whole numbers, and windows under 8192, are refused rather than silently reinterpreted. Unset/`0` means unknown. Unknown is supported **on providers that report an overflow as an error** (Anthropic, OpenAI-wire hosted APIs): the harness does no proactive compaction and instead compacts when the provider says the context is too long, then resends. Set it and the harness also compacts *before* sending, at 75% of this figure. State the input capacity, not the headline total — Anthropic reports it as `max_input_tokens` on `GET /v1/models/{id}`; the difference is what the provider reserves for the reply. There is deliberately no built-in per-model table: one is wrong the day a model ships, and a wrong window fails both ways (too high still overflows, too low silently discards context that was fitting). **Set it explicitly for `ollama`** — a local server that truncates an over-long prompt and answers 200 produces no error to react to, so the reactive path never fires and the oldest messages are dropped server-side, instructions first. The number is also passed to the adapter as `options.num_ctx`; whether the OpenAI-compatible endpoint honours that has not been verified here, so do not rely on it to raise a server-side window. |
| `AGENT_MAX_TURNS` | Runaway backstop on the agent loop's turns. Defaults to `400`. Not the operational bound on how much a run does — that is `maxApplicationsPerRun` on the Agents page. Driving one application form through the browser costs 15-25 turns. The last turns are reserved for the model to wind up in. |

**Harness binary.** `HARNESS_CLI` overrides the path to the compiled entry
point; it defaults to `/app/agent/dist/harness/cli.js`.

**Exit-code contract.** The harness's exit code is its machine interface, logged
and propagated verbatim: `0` success, `2` turn cap, `3` provider error, `4` MCP
connection failure, `5` bad configuration.

**No built-in tools.** The harness ships with **no** built-in tools — there is
no `Read`, `Write`, `WebSearch`, or `WebFetch`. Every capability the agent has
comes from the MCP servers declared in [`mcp.json`](mcp.json); if a server is
not in that config, the agent cannot reach it.

## Agents page: the schedule and enable switch

The **Agents page** is the source of truth for whether the agent runs and
when. It reads and writes the app service's agent config
(`GET`/`PUT /api/agent/config`, camelCase `enabled`/`blockedCompanies`/
`runAt`/`runDays`), which `agent/entrypoint.sh` and `agent/daily-apply.sh`
poll through the small node helper `agent/agent-config.js` — the agent image
has no `curl`, so `node` is the only HTTP client available to it.

- **Schedule** — `entrypoint.sh`'s `refresh_schedule()` re-fetches `runAt`/
  `runDays` from the config API on every pass through the run loop (at least
  every 5 minutes, so a change made on the Agents page is picked up without
  restarting the container). If the config API is unreachable or returns a
  malformed schedule, it falls back to the `RUN_AT`/`RUN_DAYS` env values
  above. `--check-schedule`'s output line reports which source it used
  (`source=config` or `source=env`).
- **Enabled flag** — `daily-apply.sh` checks `enabled` at the start of every
  run, after its other preconditions pass. `false` skips the run cleanly
  (exit 0, logged, not an error). An **unreachable** config API is not treated
  as "enabled": the run **aborts** (fails closed) rather than applying with a
  possibly-stale flag — if the app is down, the MCP tools the run depends on
  are down too, so "did not run" is the safe failure.

The operator's identity isn't configured through an env var, so it has no row
above — it's seeded straight into the data volume; see [The agent has no
identity until you seed one](#the-agent-has-no-identity-until-you-seed-one).

## Target queue

The agent's research queue of companies and roles to consider lives at
`agent/targets.md` — an **operator-supplied file, gitignored** (see
`.gitignore`), not shipped with this repo. Start from
[`agent/targets.example.md`](targets.example.md), which documents the file's
format with invented companies, and copy it to `agent/targets.md` with your
own research. The agent never reads or writes this file automatically; the
authoritative record of what has actually been applied to, screened out, or
is in cooldown is always TruthCV's own application ledger and screening
store, reached through the MCP tool surface.

## Volumes

- `agent-runs → /app/runs` — per-run logs, one file per run. Its own named
  volume, not the app's data volume: these are operator diagnostics, and without
  a volume they vanish on exactly the restart that makes you want them.

**The app's data volume is deliberately not mounted.** Every capability the
agent has arrives through the MCP tool surface — cover letters, the canonical
CV, the form answers, cooldowns, and the records it writes back. It has no
filesystem route to your data and should not acquire one.

## What the agent may and may not do

Its allow-list is hardcoded in the harness (`agent/harness/tools.ts`) and is the
TruthCV MCP tools, each granted individually — naming each one keeps the blast
radius of a new server-side tool at zero until it is granted on purpose — plus
the whole `browser` MCP server (granted as `mcp__browser`, not as individually
named tools — the upstream `@playwright/mcp` tool set is theirs to rename or
extend on a version bump). The harness has no built-in tools of its own: the
former `Read`/`Write`/`WebSearch`/`WebFetch` are gone, and only MCP tools exist
to be granted. It has no tool for approving an inference: the approve/deny gate
is the product, and the agent never stands on both sides of it. The RUNBOOK's core rules still hold —
the truthfulness rules, the cooldowns, and the rule that an application counts
as submitted only when the confirmation page says so — but its search filters
are no longer built in: they come entirely from your configured job profiles,
and a run with zero enabled profiles aborts instead of applying defaults.

## Verification

`smoke-test.sh` checks, without applying to anything:

- the compiled agent harness (`dist/harness/cli.js`) is present, non-empty, and parses under `node --check`, and the agent's files parse
- `mcp.json` is valid and declares the server the allow-list names
- **no browser is present in the image** — this is pinned as a test, so re-adding
  one turns it red
- `--check-schedule` resolves the configured slots
- `jq` is on `PATH`
- `BROWSER_MCP_URL` is reachable over HTTP — the difference between the
  `browser` service actually answering and merely being listed in
  `docker-compose.yml`
- `TRUTHCV_MCP_URL` answers
- the run log volume is writable

**Not verified, and not verifiable here:** an end-to-end application against a
real employer. Nothing has been submitted from this container. The only way to
test that is to let it apply for real — do it with `RUN_ONCE=1`, watching.
