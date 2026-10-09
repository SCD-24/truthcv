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
> sign-in.** Open **Job boards → Needs attention** in TruthCV and click Sign in; a
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
| `AGENT_API_TOKEN` | required | Shared secret (generate with `openssl rand -hex 32`). The agent always fetches its LLM credentials from the app with it at run start, via a guarded endpoint; runs abort when it is unset. |
| `RUN_AT` | `09:00,15:00` | Comma-separated `HH:MM` (24h, container TZ). Fallback only — used when the agent config API is unreachable; see below. |
| `RUN_DAYS` | `1,2,3,4,5` | Days to run, `1`=Mon … `7`=Sun. Fallback only — used when the agent config API is unreachable; see below. |
| `RUN_ONCE` | unset | `1` = run immediately and exit. |
| `TZ` | `UTC` (compose sets `TZ=${TZ:-UTC}`) | Container timezone. Also the second link in the schedule-zone fallback chain below, used only when the Agents page's `run_timezone` is unset or unreachable and `RUN_TIMEZONE` is unset. |
| `RUN_TIMEZONE` | unset → falls back to `TZ`, then `UTC` | Fallback IANA zone the `RUN_AT` slots are wall-clock times in. Full chain: the app's stored `run_timezone` (Agents page) when the config API is reachable, else `RUN_TIMEZONE`, else `TZ`, else `UTC`. Not set by `docker-compose.yml`; the fallback is applied by `entrypoint.sh` and `supervisor.js` (`agent-config.js` only reports the app's stored value, empty if absent). |
| `TRUTHCV_MCP_URL` | `http://app:8080/mcp` | The `app` service's MCP streamable-HTTP JSON-RPC tool surface (`POST /mcp`, `agenttools/mcp_app.py`). In-network only — not reachable from the host or the internet. |
| `AGENT_BROWSER_DRIVER` | `browser` | Which browser driver the agent uses. `browser` (the containerised Chromium) is currently the only supported value — kept as a validating seam so a second driver can be added later without every call site needing to change. |
| `BROWSER_MCP_URL` | `http://browser:8931/mcp` | In-network address of the `browser` compose service's MCP endpoint (see [`browser/README.md`](../browser/README.md)). Also in-network only. Used by the `browser` driver. |
| `MAX_APPLICATIONS_PER_RUN` | empty | Fallback only: `maxApplicationsPerRun` on the Agents page takes precedence. Empty in both means **no cap**, matching RUNBOOK §1 ("there is no daily quota"). Not zero. Enforced server-side on the approved-queue path (`get_approved_applications` caps and leases what it hands out); on a posting the agent discovers itself in FULL AUTO it is prompt-level only. |
| `RUN_LOG_DIR` | `/app/runs` | Where `daily-apply.sh` writes per-run logs. Must stay inside the `agent-runs` volume or logs vanish on restart. |
| `AGENT_CONTROL_PORT` | `9099` | Port the agent's `supervisor.js` control server listens on (`POST /run`, `POST /cancel`, `GET /status`, all gated by `X-Agent-Token` = `AGENT_API_TOKEN`). |
| `SESSION_SERVER_PORT` | `8932` | Port of the `browser` service's session server. `daily-apply.sh` calls it at `browser:$SESSION_SERVER_PORT` to reclaim the browser from an attended sign-in session before each run. |
| `SESSION_EVICT_TIMEOUT` | `240` (seconds) | How long `daily-apply.sh` waits for an evicted sign-in session to release the browser before aborting the run. **Must exceed the browser service's `SESSION_GRACE_MS`** (default `180000` ms = 180 s, `browser/session-server.js`) plus one 5 s poll tick and the close grace; raise them together or every run that meets an open session aborts. |

The container no longer aborts at start without an LLM credential — it logs a warning and continues; each scheduled run aborts (with a recorded reason on the Agents page) until a credential is available.

The agent runs a provider-neutral harness (`agent/harness`, compiled into the image). Configure its independent **Application agent** route under **Model routing** in the web UI using a `claude`, `codex`, or `openrouter` connection from **Model routing → Accounts**. Clearing that route uses Claude independently of the default task model: the app resolves a saved Claude sign-in or API key, with an environment credential fallback. Changes take effect on the next run. The harness also supports `ollama` when configured outside this UI. Its credentials are resolved at run start through `GET /api/agent/llm-credentials`.

### Harness configuration surface

`daily-apply.sh` invokes the harness as `node "$HARNESS_CLI"` and hands it the
provider, wire, model, credential, and auth type it resolved from the app. The
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
flag that takes precedence; `daily-apply.sh` passes the flags explicitly).
`daily-apply.sh` sets the `AGENT_LLM_*` variables from the app's credentials; set them by hand only when running the harness CLI directly.

| Env var | Meaning |
|---|---|
| `AGENT_LLM_PROVIDER` | Logical provider: `claude`, `codex`, `openrouter`, or `ollama`. |
| `AGENT_LLM_WIRE` | Wire protocol: `anthropic-messages` or `openai-chat-completions`. |
| `AGENT_LLM_MODEL` | Model identifier requested from the provider. |
| `AGENT_LLM_API_KEY` | Credential token (api key or OAuth token). May be empty only for `ollama`. Never echoed — the harness redacts it from all output. |
| `AGENT_LLM_BASE_URL` | Base URL. Required for `ollama`; optional elsewhere (falls back to the per-provider default above). |
| `AGENT_LLM_AUTH_TYPE` | How to present the token: `oauth`, `api_key`, or `url`. |
| `AGENT_MAX_TURNS` | Runaway backstop on the agent loop's turns. Defaults to `400`. Applies **per session** — each apply session daily-apply.sh runs gets its own fresh `AGENT_MAX_TURNS` budget, not a share of one run-wide total. Not the operational bound on how much a run does — that is `maxApplicationsPerRun` on the Agents page. Driving one application form through the browser costs 15-25 turns. The last turns are reserved for the model to wind up in. The harness reports how many turns remain directly on the configured finish tool's result (`turns_remaining`; `finish_application` in pipeline apply sessions), so the agent is never left guessing at the limit. |
| `AGENT_SESSION_MODE` | `daily-apply.sh` only. Unset (the default) and `pipeline` behave identically — `pipeline` is the only mode; any other value aborts the run (exit 1, with a recorded reason) before the browser or app are touched. Code performs discovery, coverage recording and screening (`pipelineCli`), then runs one short apply session per approved/passing posting, each ending with `finish_application`. Models are routed per stage (Settings agent stages → `llm_routes`, fetched into a temp `--routes-file`); `AGENT_SCREENING_*` env vars still override the screening stage. Dork recency is the `dorkRecency` setting on the Agents page. |
| `AGENT_FINISH_TOOL` / `--finish-tool` | Names the tool the harness injects `turns_remaining` into and expects to end the session: one of `finish_run`, `finish_phase`, `finish_application`; anything else is a config error (exit `5`). The harness default is `finish_run`; `daily-apply.sh` always passes `--finish-tool finish_application` for each pipeline apply session. The flag wins over the env var. |
| `AGENT_MAX_RETRIES` | Cap on consecutive retryable-error retries within one turn, before the loop gives up on a persistently failing provider call rather than retrying forever. Defaults to `12`. |
| `AGENT_MAX_RETRY_DELAY_MS` | Ceiling on a single retry's backoff delay, in ms, so a provider effectively saying "retry in hours" fails fast instead of parking an unattended run. Defaults to `300000` (5 minutes). |
| `AGENT_MAX_TOOL_RESULT_CHARS` | Caps a single MCP tool result's character length at the moment it is inserted into the conversation. Defaults to `24000`. An over-long result — a full-page browser snapshot, a long file read — is truncated with an explicit marker naming how many characters were cut and instructing the model to re-request a narrower view, so it never receives silently partial data. Must be a positive integer. |
| `AGENT_PROMPT_CACHE` | Toggles Anthropic prompt-cache `cache_control` breakpoints (the tools block plus the first and last message) on the **Anthropic wire only**. Defaults to `true`. Set to `false` to disable caching entirely if runs are spaced further apart than the cache's 5-minute TTL, where the cache-write cost (1.25x) could exceed the savings. Has no effect on the OpenAI-compatible wire, which relies on automatic prefix caching instead. |
| `AGENT_MAX_TOOL_CONCURRENCY` | Max non-browser tool calls one turn dispatches concurrently against the shared truthcv MCP server. Defaults to `4`. Browser tool calls always run one at a time regardless of this value, because the browser server drives a single Chromium profile with one holder. Must be a positive integer. |
| `AGENT_BROWSER_SESSIONS` | Retired for production harvest: ignored, not forwarded by Compose. `harvest_postings` always works boards serially through the primary browser MCP connection and persistent signed-in profile; setting this value cannot re-enable concurrent sessions or tabs. The old session-per-worker and tab modes remain dormant helper code only. |
| `AGENT_SCREENING_MODEL` | Model identifier for the `screen_posting` built-in tool's own, separate provider adapter — an isolated, typically-cheaper subagent call that screens one discovered posting against a job profile's criteria instead of reasoning through every hard filter in the main loop's own context (see `RUNBOOK.md` §5). **Defaults to `AGENT_LLM_MODEL`** (the main model) when unset, so an operator who configures nothing keeps today's behaviour exactly: one model doing both jobs. |
| `AGENT_SCREENING_PROVIDER` | Logical provider for the screening adapter: `claude`, `codex`, `openrouter`, or `ollama`. Defaults to `AGENT_LLM_PROVIDER` when unset. |
| `AGENT_SCREENING_WIRE` | Wire protocol for the screening adapter. Defaults to `AGENT_LLM_WIRE` when unset. |
| `AGENT_SCREENING_API_KEY` | Credential token for the screening adapter. Defaults to `AGENT_LLM_API_KEY` when unset. Never echoed — redacted from all output like `AGENT_LLM_API_KEY`. |
| `AGENT_SCREENING_BASE_URL` | Base URL for the screening adapter. Defaults to `AGENT_LLM_BASE_URL` when unset. |
| `AGENT_SCREENING_AUTH_TYPE` | How to present the screening token: `oauth`, `api_key`, or `url`. Defaults to `AGENT_LLM_AUTH_TYPE` when unset. |
| `AGENT_ROUTES_FILE` / `--routes-file` | Path to the per-stage model routes JSON; `daily-apply.sh` fetches it from the app into a temp file and passes `--routes-file`. Unreadable or unset means no routes. An explicit `AGENT_LLM_*` / flag value overrides only its own field of the apply route. |
| `MCP_CONFIG_PATH` / `--mcp-config` | Path to the MCP config. Defaults to `mcp.json` in the working directory; `daily-apply.sh` passes `--mcp-config` from its own `MCP_CONFIG` (default `/app/agent/mcp.json`). |

The model's **input** context window is no longer an operator-stated env var: the harness discovers it itself, per model, directly from the provider (OpenRouter's `/models` listing, Anthropic's `max_input_tokens` on `GET /v1/models/{id}`, Ollama's `/api/show`, or Codex's `/models` catalog reading `context_window` for the matching model slug — falling back to OpenAI's `/v1/models/{id}` when Codex is configured with an API key, which usually reports no context length) at startup, and uses that figure to trigger proactive compaction at 75%. When a provider cannot report one, or a discovery call fails or times out, the harness falls back to a conservative default (32768 tokens), logging that the fallback is in effect. The reactive path — compacting when the provider itself says the context is too long, then resending — still runs on top of this **on providers that report an overflow as an error** (Anthropic, OpenAI-wire hosted APIs), and is what rescues a discovered or fallback figure that turns out too high. For `ollama`, the discovered (or fallback) window is also passed to the adapter as `options.num_ctx`; whether the OpenAI-compatible endpoint honours that has not been verified here, so do not rely on it to raise a server-side window.

**Harness binary.** `HARNESS_CLI` overrides the path to the compiled entry
point; it defaults to `/app/agent/dist/harness/cli.js`.

**Exit-code contract.** The harness's exit code is its machine interface, logged
and propagated verbatim: `0` success — the loop ended cleanly *and* the agent
executed the **configured finish tool** (`--finish-tool` / `AGENT_FINISH_TOOL`;
`finish_run` by default, `finish_application` in the apply sessions
`daily-apply.sh` launches) before stopping — `2` turn cap, `3` provider error,
`4` MCP connection failure, `5` bad configuration (including an unrecognised
finish-tool name), `6` the loop ended cleanly but the configured finish tool was
never executed, so the session was abandoned without reporting an outcome. In
pipeline mode `daily-apply.sh` treats `1`, `2` and `6` from one apply session as
a per-posting failure (logged and counted, the run continues) and `3`/`4`/`5`
as systemic (the apply loop stops).

**Feed-first saved screening.** After the approved Phase 0 queue, the feed
lists metadata and URLs, not guaranteed posting bodies. Retrieve full posting
text (serial browser access if needed), then call `screen_and_record_posting`
for each feed role before direct-board/dork discovery or new applications.
It screens and persists through the allow-listed `record_screening` MCP tool in
one call: its compact stored outcome (id, verdict, screening_blocker, created,
actionable) omits the full posting text; only `actionable:true` permits a new
application. `created:false` means skip, even when an unread placeholder was
replaced, and success must not be recorded again. On an error, stop acting on
that posting, not the entire run; continue other work and coverage. Ask the
operator to open `GET /api/screenings` on the TruthCV app origin (navigate to
`/api/screenings` in their browser) and inspect the returned JSON array's `url`
fields for the posting URL to confirm whether a record exists. The `/screenings`
UI does not display the URL; there is no agent screening lookup tool. Do not
retry or rescreen automatically; use `record_screening` manually only after
the operator confirms no record exists. The read-only `screen_posting` remains
available for manual screening followed by a separate `record_screening`.
A raw-snapshot harvest `needs_review` is internal only: recover postings as
`searched`/`llm`, mark `empty` only on explicit zero-result evidence, otherwise
record `extraction_failed` with the reason. The `rawSnapshot` is an excerpt;
if `rawSnapshotTruncated` is true or the note says it was omitted, re-harvest
that board alone in its own call first. For dorks, pass the Google search URL
(with the `site:` query) as the board url; links to the `site:` target are
extracted automatically. Phase 0, filters, caps and
autonomy are unchanged. `harvest_postings` takes an optional `location`,
typed into the board's own detected location field (never folded into
`keywords`); a location neither it nor its known local-language aliases ever
gets confirmed by the board's own location control comes back `blocked` with
`blockKind: "location"`. A board with no on-page search box instead carries
its own `searchUrl` templated search URL (`{keywords}` required, `{location}`
optional); the built URL replaces `url` outright, is navigated to directly,
and the snapshot is classified with no search-box typing at all.
`blockKind: "timeout"` means navigation timed out twice in a row (an initial
attempt and one retry) — the page did not load — and still maps to
`status="blocked"`; an absent `blockKind` still means an internal failure.

**Narrow built-in tools.** `read_runbook_section` returns one named section of
`RUNBOOK.md` from the image and takes no path argument, so it opens no general
filesystem read. `screen_posting` screens via its configured provider adapter;
`harvest_postings` uses only allow-listed browser tools on the primary MCP
connection, serially. There is no `Read`, `Write`, `WebSearch`, or `WebFetch`.
Other capabilities come from the MCP servers declared in [`mcp.json`](mcp.json);
if a server is not in that config, the agent cannot reach it.

## Agents page: the schedule and enable switch

The **Agents page** is the source of truth for whether the agent runs and
when. It reads and writes the app service's agent config
(`GET`/`PUT /api/agent/config`, camelCase `enabled`/`blockedCompanies`/
`runAt`/`runDays`/`runTimezone`), which `agent/entrypoint.sh` and `agent/daily-apply.sh`
poll through the small node helper `agent/agent-config.js` — the agent image
has no `curl`, so `node` is the only HTTP client available to it.

- **Schedule** — `entrypoint.sh`'s `refresh_schedule()` re-fetches `runAt`/
  `runDays`/`runTimezone` from the config API on every pass through the run
  loop (at least
  every 5 minutes, so a change made on the Agents page is picked up without
  restarting the container). If the config API is unreachable or returns a
  malformed schedule, it falls back to the `RUN_AT`/`RUN_DAYS` env values
  above. `--check-schedule`'s output line reports which source it used
  (`source=config` or `source=env`) and the schedule zone it resolved. The
  `runAt` slots are **wall-clock times in `runTimezone`** (default `UTC`), so
  a `09:00` slot with `Europe/Berlin` fires at 07:00Z in winter and 08:00Z
  under DST. The long-running loop is `supervisor.js`; `--check-schedule` is
  an advisory preview and can differ by an hour on a DST transition day.
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

## Read-only run diagnostics over MCP

The app's bearer-gated `/mcp/diagnostics` surface offers three additional
**read-only** tools: `get_agent_status()`,
`get_run_events(run_id, limit=50, before_sequence=null)`, and
`get_run_logs(run_id, limit=50, before_offset=null)` (both page limits 1–200;
`run_id` is a retained run id of 1–80 ASCII letters/digits/underscores/hyphens).
Use `list_runs` to find a stored run id (`get_run` carries the per-run detail), then `get_agent_status` for current
supervisor state, `get_run_events` for metadata-only execution boundaries, and
`get_run_logs` for classified, sanitized excerpts of the agent's run log.
Page events backward using `next_before_sequence` as `before_sequence` and
log excerpts using `next_before_offset` as `before_offset`; null cursors mean
no older page. No tool starts/cancels runs or returns raw logs. This surface
requires `DIAGNOSTICS_MCP_TOKEN` as the
remote client's Bearer token; it is **not** the supervisor's `AGENT_API_TOKEN`.
The app uses its existing `AGENT_API_TOKEN` to make GET-only requests to the
agent at `agent:AGENT_CONTROL_PORT` (default 9099), on the private Compose
network. Use the existing shared agent token in app and agent; no additional
port exposure or shared volume mount is required. Rebuild both services to
include the new internal logs route before using `get_run_logs`.

`get_agent_status` reports `observed_at`, `reachability`, `availability`, a
sanitized `reason` on failure, and allowlisted `/status` fields (`running`,
`cancelling`, `currentRunId`, `lastRunId`, last start/finish/exit/cancellation,
`scheduleEnabled`). `get_run_events` validates the id against stored runs and
returns schema version 1, run id, timestamps, availability/reason, reachability,
`ownership`, `running`, `currentRunId`, bounded chronological `events`,
`last_activity_at`, `active_operations`, `active_truncated`, `truncated`, and
the pagination cursor. Each event holds only sequence, timestamp, operation id,
phase (`registry_refresh`, `compaction`, `model`, `tool`, `backoff`), boundary status
(`start`, `success`, `error`), and optional elapsed milliseconds, safe tool
name, turn/retry/backoff numbers, and active-operation/truncation metadata.
`get_run_logs` returns `schema_version: 1`, `run_id`, `availability`
(`available` or `unavailable`), sanitized `reason` (or null), `reachability`
(`unknown`, `reachable`, or `unreachable`), `excerpts` (newest offsets first),
`next_before_offset`, `truncated`, and `omitted`. Each excerpt has a byte
`offset`, `observed_at` (canonical UTC millisecond timestamp of **reading** the
log, not the event's occurrence), a finite `category`, and a summary
reconstructed from a fixed local template. Categories are `precondition`,
`configuration`, `mcp_connection`, `provider_error`, `fatal`, `harness_exit`,
`harness_error`, `provider_http`, `provider_network`, `loop_event`, `done`, and
`tool_failure`. Only category-appropriate fields may appear: `exit_code`
(0–255) for harness exits or done; `provider` (`anthropic`, `openai`,
`openai_responses`, `openrouter`, `ollama`) for provider HTTP/network errors;
`http_status` (100–599) for provider HTTP errors; `retryable` (boolean) and
`retry_after_ms` (0–3,600,000) for provider HTTP/network or harness errors;
`kind` (`compaction`, `retry`, `reflection`, `emptyTurn`, `turnCapReached`,
`wrapUp`, `stop`) and `turn` (0–1,000,000) for loop events; `stop_reason`
(`toolCalls`, `end`, `length`, `error`, `aborted`, `turnCapReached`) and `turns`
(0–1,000,000) for done. All numeric values are integers, not booleans.
Optional fields can be absent; do not infer their values. An available page
can have zero excerpts even when scanning encountered only filtered-out or
incomplete records. `omitted: true` means some source records were skipped
(e.g. unrecognized lines, oversized records or a partial append); it does
not count them. `truncated` is exactly whether `next_before_offset` is
non-null: a scan can advance its cursor through **empty filtered pages**;
continue paging while a cursor is returned. Neither empty excerpts nor a null
cursor establish that the run had no errors.

A missing log yields `availability: unavailable`, `reason: missing`; a log
that cannot be trusted/read yields `reason: unreadable` (including ambiguous
multiple matching filenames, symlinks/nonregular files, or a directory with
more than 1024 entries). The directory cap fails closed even if a matching
file exists; it does not change retention. Runs retained by the app may lack
an agent log (e.g. a historical file removed from the agent's own volume).
An invalid request or unknown stored run returns `invalid_request` or
`unknown_run` before contacting the agent. Transport and validation failures
use sanitized reasons including `missing_token`, `token_mismatch`,
`unreachable`, `timeout`, `old_endpoint`, `upstream_error`, and
`malformed_response`; no upstream body or exception is returned. Unlike
`get_run_events`, log excerpts **do not establish live ownership**: use
`get_agent_status` / `get_run_events` separately for current supervisor state.
The projection cannot recover an error that was never recorded; a historical
run may still yield only a generic classification or nothing at all.

No model prompt/response, tool arguments/results, URLs, secrets, raw exception
text, HTTP body, or raw run log crosses this boundary. Diagnostic telemetry
alone is capped at 2 MiB per new run in the existing `agent-runs` volume;
raw run logs do not inherit that retention cap. Both readers cap replies at
256 KiB, and the app caps received bytes before parsing. Log projection reads
backward in 64 KiB windows, scanning at most 512 KiB plus 8 KiB per request,
and discards records over 8 KiB. These bounds limit work, not filesystem
latency: like the metadata reader, the log reader uses synchronous filesystem
calls, so a stalled agent volume can delay other supervisor requests.
Older runs have no backfilled telemetry. Top-level `active_truncated` reports
whether the latest live active snapshot omitted operations (more than 128),
even when `before_sequence` selects an empty/older event page; it is false
for historical or unavailable telemetry. `truncated` separately describes
event retention/pagination. Truncation and an absent page are not proof of
inactivity.

Live telemetry also requires the current child's private inherited fd 3 health
pipe: the harness sends only version, health, and latest *persisted* sequence,
with a 1-second heartbeat; the supervisor trusts it for at most 5 seconds of
monotonic time. The pipe is not an endpoint, port, mount, or durable artifact.
A disk write failure invalidates the live snapshot even if removing a previously
valid NDJSON file also fails. A missing, closed, malformed, oversized, expired,
or cancelled channel returns `telemetry_unavailable` with empty events and
active operations for the current run, while retaining its `running` and
`currentRunId`. Detection is bounded by the lease, **not instantaneous**; an
elapsed boundary or unavailable telemetry is not itself a stall diagnosis.
Historical retained events remain readable without live active snapshots;
standalone CLI runs without the private channel retain their normal execution
and diagnostic-file behaviour, but the supervisor never trusts their file as
live telemetry. A supervisor restart cannot reconstruct a health lease from
persisted files.

Only `running: true` **and** a matching `currentRunId` establish live
`ownership: active`. Historical events, a run-store `running` counter, or a
failed/unreachable supervisor probe do not establish a live process;
`ownership: unknown` on a failed probe is not an idle verdict. A valid
supervisor response with missing/malformed telemetry still reports its
`running`, `currentRunId`, and live ownership, without claiming an active
snapshot. Reasons such as `missing_token`, `token_mismatch`, `unreachable`,
`timeout`, `old_endpoint`, `unknown_run`, `malformed_response`, and `absent_telemetry`
name distinct remediation paths without exposing upstream details. Events
mark *outer* tool execution boundaries: a long compound built-in (for
example `screen_and_record_posting`) is timed as one outer tool call, not
its nested network/model/persistence steps. A long elapsed time or missing
terminal event is evidence to investigate, **not** an automatic stall
diagnosis; check ownership and later events before drawing conclusions.

After upgrading, **rebuild and redeploy both app and agent images** with
matching internal `AGENT_API_TOKEN` values and refresh/reconnect the remote MCP
client so tool discovery lists all twelve read-only tools (including `get_run_logs`).
The diagnostics client's bearer `DIAGNOSTICS_MCP_TOKEN` remains separate; no
new port or shared volume mount is needed. The new internal
`GET /diagnostics/runs/{run_id}/logs` route uses the existing token gate.
For a smoke check, start a **new** run (a run started before upgrade will not
have these events). Call `get_agent_status` while it runs and
confirm `running: true` and `currentRunId` equals the new run id. Poll
`get_run_events` for that id: while the model or a tool waits, expect a
`model` or `tool` `start` boundary and an active operation; after completion,
expect a matching `success` or `error` terminal boundary with `duration_ms`.
When the process exits, status should stop reporting that run as current and
subsequent event reads should show `ownership: inactive`, with no live active
operations. If telemetry is `absent_telemetry`, check that the run really
started on the redeployed agent; if the supervisor is unreachable, investigate
the network/token first rather than inferring the run has stopped. A live
run can apply for real — follow the `RUN_ONCE=1` warning above.

## How discovery works

Discovery is code-driven (`agent/harness/pipeline/discover.ts`, run by
`pipelineCli discover-screen`), not model-driven. From the app's `job_config` it
runs three channels: API feed postings, direct boards (searched on-site), and
Google dorks. One `record_discovery_coverage` is recorded per composed entry.

**Dork construction** (`agentconfig/dorks.py`, `compose_queries`):

- **Per title, not per keyword.** Queries are built from each enabled profile's
  job titles (`title_keywords`; else keywords ending in a title noun such as
  engineer/developer/analyst; else the raw keywords), one `site:<board>` query
  per board. API-backed, direct-mode and disabled boards get no dork.
- **Pipe-grouped, chunked.** Titles are OR-grouped as `("A" | "B C")` and packed
  greedily into chunks that fit Google's 32-word limit after the fixed
  `site:`, location, remote and recency terms (a single title too long to fit
  still gets its own chunk, so that query can exceed the limit); one query per chunk per board,
  ordered chunk-major. No title is dropped.
- **Negatives.** The profile's rejected role types are appended as `-"term"` in whatever word budget the titles leave; any that would
  overflow are dropped. Screening still enforces role types.
- **Quoting.** Every term is quoted for exact match; embedded double quotes are
  stripped from titles, locations and negatives; terms empty after stripping are
  dropped.
- **Recency.** The `dorkRecency` setting (Agents page: `d`/`w`/`m`/`y`/`none`)
  adds a trailing `after:YYYY-MM-DD` operator counted back 1/7/30/365 days from
  today (UTC); `none` omits it, and unset or invalid values behave as `w`.
- Queries are interleaved round-robin across profiles and de-duplicated by URL.
- **Pacing.** Dorks run one at a time with a randomized 15–30 s pause between
  searches, measured from the previous search even across runs (state in
  `--dork-state-file`, kept as `dork-state.json` in the run log dir; absent flag
  = defaults, nothing persisted). Searching runs alongside screening: the browser
  lock is held only while a query is harvested, never while waiting. After two
  consecutive Google blocks/CAPTCHAs searching pauses for a 30-minute cooldown;
  the queries not searched are recorded as `deferred` (never `skipped`, and a
  deferral is not a coverage shortfall) and are searched first in the next run.
  A Google consent page is attempted once.

**Per-source funnel** (`pipeline/funnel.ts`). Every discovered URL gets exactly
one outcome — `previously_screened`, `not_a_posting`, `duplicate`, `failed`,
`for_review`, `rejected` or `blocked` — rolled up per discovery source and in
total, and stored with `record_source_funnel`. A URL that reached no outcome is
counted `failed` ("no outcome recorded").

**Transient fetch failures** (`pipeline/fetchPosting.ts`, `screenStage.ts`). A
posting that cannot be loaded at all (navigate/snapshot error) is a `failed`
fetch: it is reported as a run error and a `failed` funnel outcome, and no
screening blocker is recorded for it. A page that loads but is thin is
re-snapshotted up to 4 times (2 s apart); if still unreadable it is recorded as
an `unreadable` blocker (after following one onward link, if there is one) or
`login_required` for a sign-in wall.

**LinkedIn capture.** LinkedIn postings rely on the persisted signed-in browser
profile (Job boards → Needs attention → Sign in). The fetch waits until the `Primary content`
region is filled and no "loading job details" marker remains; an
authwall/login/checkpoint URL is recorded as a `login_required` sign-in wall,
and a job that never renders as `unreadable` ("LinkedIn job details did not
load").

## What the agent may and may not do

Its allow-list is hardcoded in the harness (`agent/harness/tools.ts`) and is the
TruthCV MCP tools, each granted individually — naming each one keeps the blast
radius of a new server-side tool at zero until it is granted on purpose — plus
an enumerated allow-list of `browser` MCP server tools (`BROWSER_ALLOWED_TOOL_NAMES`
in `agent/harness/tools.ts`, mirrored in `agent/mcp.json`'s `browser.allowedTools`):
only the tool names this RUNBOOK actually calls are granted, not the whole
upstream `@playwright/mcp` server. That browser allow-list is itself split
into a REQUIRED set (the ten tools the RUNBOOK's step-by-step browser
instructions call directly) and an OPTIONAL set (the four `browser_tab_*`
tools retained in the allow-list for model-issued calls, not used by
production `harvest_postings`). The harness fails loudly at startup,
before any run turn, if a REQUIRED name is missing from what the `browser`
server actually advertises — an upstream rename must never silently disable a
tool mid-run. A missing OPTIONAL tab tool does **not** fail startup: those
names are this workspace's best guess at what the pinned `@playwright/mcp`
calls its tab tools — the package is installed into the `browser` image at
build time and is not vendored here, so the names could not be verified
against it. Whether or not the `browser` server advertises them,
production `harvest_postings` harvests boards serially, one at a time, on the
primary MCP connection and persistent signed-in profile — same per-board
result shape and outcome classification; its serial mode is logged (never
page content). The tab-per-board and session-per-worker helper modes remain
in code for direct callers/tests, but production dispatch cannot reach them.
The harness has no tool for approving an inference: the approve/deny gate
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
