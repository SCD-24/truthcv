# The unattended application agent

A second container alongside TruthCV's `app` service. On a schedule it runs
headless Claude Code against [`RUNBOOK.md`](RUNBOOK.md), finds roles, applies to
them in a real browser, and records what it did through TruthCV's own tools.

It is deliberately a separate service and a separate image: a browser session
going wrong must never take the wizard down with it, and the wizard's image
stays free of agent tooling.

## The browser is on the host. On purpose.

**This image contains no browser.** No Chrome, no Chromium, no Xvfb, no
Playwright — and re-adding one is not a fix.

The agent drives the operator's real, already-logged-in Chrome on the **host**, reached
through the Interceptor daemon over a unix socket bind-mounted into the
container (`INTERCEPTOR_SOCKET`, see [`mcp.json`](mcp.json)). Unattended applying
depends entirely on sessions that already exist in that browser — ATS accounts,
SSO, saved profiles. A container's own browser starts blank and logged out, so
it cannot do this job; it can only look like it can, right up to the point where
a submission silently fails.

This is the one place TruthCV diverges from the retired Jobs container, which
ran its own Chrome under Xvfb. That trade was reconsidered and reversed.

> **Known gap — the agent has no browser driver yet.** The Jobs repo never
> contained the Interceptor MCP server; it relied on one declared in the
> operator's personal Claude config plus a Chrome extension its own docs record
> as not installed. `mcp.json` therefore defaults `interceptor` to a
> **placeholder** command. Until you point `INTERCEPTOR_MCP_COMMAND` at the real
> server on your host, every run will abort at browser attach. `smoke-test.sh`
> tells you whether the socket is genuinely live before you find out the hard
> way.

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

The agent is behind a compose profile, so a bare `docker compose up` does not
start it:

```bash
export ANTHROPIC_API_KEY=...           # never commit this
docker compose --profile agent build agent
docker compose --profile agent up -d agent      # scheduled loop
docker compose --profile agent logs -f agent
```

Check the schedule without waiting for it — this starts nothing and applies to
nothing:

```bash
docker compose --profile agent run --rm \
  --entrypoint /app/agent/entrypoint.sh agent --check-schedule
```

Run the smoke test — also submits nothing (see [Verification](#verification)):

```bash
docker compose --profile agent run --rm \
  --entrypoint /app/agent/smoke-test.sh agent
```

One immediate run:

```bash
docker compose --profile agent run --rm -e RUN_ONCE=1 agent
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
| `TRUTHCV_MCP_URL` | `http://app:8080/mcp` | The `app` service's MCP tool surface. In-network only — not reachable from the host or the internet. |
| `INTERCEPTOR_SOCKET` | `/tmp/interceptor.sock` | Host socket for the browser, bind-mounted at the same path inside. |
| `INTERCEPTOR_MCP_COMMAND` | `interceptor-mcp` | **Placeholder.** The command that serves that socket — see the gap noted above. |
| `MAX_APPLICATIONS_PER_RUN` | empty | Empty means **no cap**, matching RUNBOOK §1 ("there is no daily quota"). Not zero. |

The agent runs the Claude Code CLI, so the **Model** setting on the Agents page accepts only the Claude connection — other providers are filtered out by design.

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

- `${INTERCEPTOR_SOCKET}` — the host browser socket, bind-mounted in. Without it
  there is no way to apply, and `daily-apply.sh` aborts rather than starting a
  run it cannot finish.
- `agent-runs → /app/runs` — per-run logs, one file per run. Its own named
  volume, not the app's data volume: these are operator diagnostics, and without
  a volume they vanish on exactly the restart that makes you want them.

**The app's data volume is deliberately not mounted.** Every capability the
agent has arrives through the MCP tool surface — cover letters, the canonical
CV, the form answers, cooldowns, and the records it writes back. It has no
filesystem route to your data and should not acquire one.

## What the agent may and may not do

Its allow-list (`daily-apply.sh`) is the six TruthCV MCP tools, the three
interceptor browser tools, and `Read`/`Write`/`WebSearch`/`WebFetch`. It has no
tool for approving an inference: the approve/deny gate is the product, and the
agent never stands on both sides of it. Everything the RUNBOOK carried over from
the Jobs runbook still holds — the six filters, the truthfulness rules, the
cooldowns, and the rule that an application counts as submitted only when the
confirmation page says so.

## Verification

`smoke-test.sh` checks, without applying to anything:

- the `claude` CLI is present and the agent's files parse
- `mcp.json` is valid and declares both servers the allow-list names
- **no browser is present in the image** — this is pinned as a test, so re-adding
  one turns it red
- `--check-schedule` resolves the configured slots
- the interceptor socket is not merely mounted but **accepts a connection**, which
  is the difference between a working host daemon and a stale socket file
- `TRUTHCV_MCP_URL` answers
- the run log volume is writable

**Not verified, and not verifiable here:** an end-to-end application against a
real employer. Nothing has been submitted from this container. The only way to
test that is to let it apply for real — do it with `RUN_ONCE=1`, watching.
