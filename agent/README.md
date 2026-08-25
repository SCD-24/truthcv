# The unattended application agent

A second container alongside TruthCV's `app` service. On a schedule it runs
headless Claude Code against [`RUNBOOK.md`](RUNBOOK.md), finds roles, applies to
them in a real browser, and records what it did through TruthCV's own tools.

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

> **First run against a login-walled site (SSO, CAPTCHA, SMS MFA) needs a
> one-time manual sign-in.** Watch or drive the real Chromium through the
> noVNC viewport at http://localhost:5628; its profile persists on the named
> volume `browser-profile`, so the session survives container restarts and
> you should not need to sign in again. See
> [`browser/README.md`](../browser/README.md) for detail.

### The other driver: your own Chrome, via Interceptor

If your host runs [Interceptor](https://interceptor.ai), you can skip the
containerised browser and the noVNC sign-in entirely and drive the Chrome you
are *already logged into*:

```bash
docker compose -f docker-compose.yml -f docker-compose.interceptor.yml up
```

That overlay flips `AGENT_BROWSER_DRIVER` to `interceptor` and bind-mounts two
host paths: the `interceptor` binary (read-only, at
`/opt/interceptor/bin/interceptor`) and the daemon's unix socket. The `claude`
CLI then spawns `interceptor mcp serve` over stdio inside the agent container;
that subprocess shells to the real `interceptor <verb>` command, which dials the
socket to reach the host daemon, which drives Chrome via native messaging.

The two drivers are mutually exclusive by design — `daily-apply.sh` grants only
the selected one's tools, because two ways to drive a browser with no rule
saying which is how an unattended run applies from the wrong session.

The bind mounts live in an overlay rather than in `docker-compose.yml` because
their sources exist only on a host that actually runs Interceptor, and Docker
answers a missing bind-mount source by silently creating a *directory* at the
target — so mounting them unconditionally would break `docker compose up` for
everyone else. For the same reason this driver is opt-in rather than the
default: it depends on host state this repo neither controls nor can test in
CI, while the `browser` service is self-contained.

**Run the smoke test before trusting it.** The binary is compiled on your host
and has to load under the agent image's glibc, which is not a given:

```bash
docker compose -f docker-compose.yml -f docker-compose.interceptor.yml \
  run --rm --entrypoint /app/agent/smoke-test.sh agent
```

It checks the binary loads, that `interceptor mcp serve` announces `serving over
stdio`, and that the socket accepts a real connection.

#### Safety tiers

Interceptor classifies its own operations. `read` and `mutate` are permitted by
default; `destructive` and arbitrary-exec operations are refused unless you opt
into them via `INTERCEPTOR_MCP_ALLOW`. Filling and submitting an ATS form is
`mutate`, so **leave `INTERCEPTOR_MCP_ALLOW` empty for an unattended
submitter** — there is nothing it needs that is not already allowed, and
widening it grants an unsupervised agent powers no one is watching.

Keep `INTERCEPTOR_MCP_FENCE=on`. Job postings are attacker-controlled text that
the agent reads and acts on, which is the textbook prompt-injection setup; the
fence is what stands between a booby-trapped posting and your real browser
session.

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
| `AGENT_BROWSER_DRIVER` | `browser` | Which browser the agent may drive: `browser` (the containerised Chromium) or `interceptor` (your host Chrome). Only the selected driver's tools are granted to `claude`. |
| `BROWSER_MCP_URL` | `http://browser:8931/mcp` | In-network address of the `browser` compose service's MCP endpoint (see [`browser/README.md`](../browser/README.md)). Also in-network only. Used by the `browser` driver. |
| `INTERCEPTOR_BIN` | `/opt/interceptor/bin/interceptor` | Where the Bun-compiled Interceptor binary is mounted *inside* the container; `claude` spawns it as a stdio MCP server. Mounted by `docker-compose.interceptor.yml`. |
| `INTERCEPTOR_BIN_HOST` | `${HOME}/.local/bin/interceptor` | The *host* path that mount reads from. Set it to your own — `command -v interceptor`. |
| `INTERCEPTOR_SOCKET` | `/tmp/interceptor.sock` | The Interceptor CLI-to-daemon IPC socket, bind-mounted at the same path inside and out. The daemon listens on the host; the mount only carries the channel in. |
| `INTERCEPTOR_MCP_ALLOW` | empty | Safety-tier opt-in. Empty already permits `read` and `mutate`, which covers filling and submitting a form. **Leave it empty for an unattended submitter**; widening it grants `destructive` and arbitrary-exec powers to a process no one is watching. |
| `INTERCEPTOR_MCP_FENCE` | `on` | Prompt-injection protection while reading job postings — attacker-controlled text the agent acts on. Keep it on. |
| `INTERCEPTOR_MCP_GROUP` | `truthcv-agent` | Group scope recorded in the daemon's own audit trail. |
| `MAX_APPLICATIONS_PER_RUN` | empty | Empty means **no cap**, matching RUNBOOK §1 ("there is no daily quota"). Not zero. |
| `RUN_LOG_DIR` | `/app/runs` | Where `daily-apply.sh` writes per-run logs. Must stay inside the `agent-runs` volume or logs vanish on restart. |

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

- `agent-runs → /app/runs` — per-run logs, one file per run. Its own named
  volume, not the app's data volume: these are operator diagnostics, and without
  a volume they vanish on exactly the restart that makes you want them.

**The app's data volume is deliberately not mounted.** Every capability the
agent has arrives through the MCP tool surface — cover letters, the canonical
CV, the form answers, cooldowns, and the records it writes back. It has no
filesystem route to your data and should not acquire one.

## What the agent may and may not do

Its allow-list (`daily-apply.sh`) is the eleven TruthCV MCP tools, the whole
`browser` MCP server (granted as `mcp__browser`, not as individually named
tools — the upstream `@playwright/mcp` tool set is theirs to rename or extend
on a version bump), and `Read`/`Write`/`WebSearch`/`WebFetch`. It has no
tool for approving an inference: the approve/deny gate is the product, and the
agent never stands on both sides of it. The RUNBOOK's core rules still hold —
the truthfulness rules, the cooldowns, and the rule that an application counts
as submitted only when the confirmation page says so — but its search filters
are no longer built in: they come entirely from your configured job profiles,
and a run with zero enabled profiles aborts instead of applying defaults.

## Verification

`smoke-test.sh` checks, without applying to anything:

- the `claude` CLI is present and the agent's files parse
- `mcp.json` is valid and declares both servers the allow-list names
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
