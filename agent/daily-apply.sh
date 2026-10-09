#!/usr/bin/env bash
# Daily job-application run for TruthCV's unattended agent (agent/Dockerfile,
# docker-compose.yml `agent` service, plan agent-container-and-schedule task
# t-2). Ported from the retired Jobs project's bin/daily-apply.sh, moved off
# that project's filesystem and onto TruthCV's MCP tool surface.
#
# Preconditions are checked first and the run aborts loudly rather than
# half-working: applying to jobs with a broken browser session is worse than
# not running at all.

set -uo pipefail

RUN_LOG_DIR="${RUN_LOG_DIR:-/app/runs}"
RUNBOOK="${RUNBOOK:-/app/agent/RUNBOOK.md}"
PROMPT_FILE="${PROMPT_FILE:-/app/agent/prompt.md}"
MCP_CONFIG="${MCP_CONFIG:-/app/agent/mcp.json}"
# The provider-neutral agent harness (agent/harness, compiled to
# dist/harness/cli.js by agent/package.json's `build`) is what actually drives
# the run — it replaces the CLI this script used to invoke. Overridable for out-of-container
# harness testing.
HARNESS_CLI="${HARNESS_CLI:-/app/agent/dist/harness/cli.js}"
# Which browser driver this run uses. `browser`, the self-contained
# containerised Chromium, is currently the only supported value - the
# variable is kept deliberately as a validating seam so a second driver can
# be added later without every call site needing to change.
AGENT_BROWSER_DRIVER="${AGENT_BROWSER_DRIVER:-browser}"

# The containerised Chromium's MCP endpoint (docker-compose.yml `browser`
# service, browser/Dockerfile). Same default as agent/mcp.json's
# ${BROWSER_MCP_URL:-...} expansion, so the probe below and the server the
# harness actually dials cannot drift apart.
BROWSER_MCP_URL="${BROWSER_MCP_URL:-http://browser:8931/mcp}"

STAMP="$(date +%Y-%m-%d_%H%M)"

# TRUTHCV_RUN_ID identifies this run to the run store (runs/store.py) via the
# start_run/finish_run/record_run_note MCP tools. The supervisor (supervisor.js)
# mints one and passes it through the environment for a scheduled run; a
# manual invocation with no supervisor gets one generated here so it is still
# accountable.
TRUTHCV_RUN_ID="${TRUTHCV_RUN_ID:-$(date +%s)-$$}"

# Pipeline is the only mode: code discovers/screens; one short apply session
# per posting. The old single/per-channel session modes were removed, so any
# other AGENT_SESSION_MODE is rejected (set it to 'pipeline' or leave it unset).
if [[ -n "${AGENT_SESSION_MODE:-}" && "${AGENT_SESSION_MODE:-}" != "pipeline" ]]; then
  mkdir -p "$RUN_LOG_DIR"
  REASON_FILE="$RUN_LOG_DIR/${TRUTHCV_RUN_ID}.reason"
  msg="AGENT_SESSION_MODE single/per-channel were removed; pipeline is the only mode"
  printf '%s\n' "$msg" >"$REASON_FILE" 2>/dev/null || true
  echo "ABORT: $msg" >&2
  exit 1
fi

mkdir -p "$RUN_LOG_DIR"
RUN_LOG="$RUN_LOG_DIR/run_${STAMP}_${TRUTHCV_RUN_ID}.log"

log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$RUN_LOG"; }

# Where this run leaves an operator-readable sentence explaining an early exit.
# agent/supervisor.js reads (and unlinks) it when the child exits and puts it on
# the run record's stopped_reason. Every abort() below exits 1, so the exit code
# alone cannot say which precondition failed, and "run aborted, see the log"
# sends the operator hunting through a file when the sentence already exists.
REASON_FILE="$RUN_LOG_DIR/${TRUTHCV_RUN_ID}.reason"

# Best-effort, like every other part of run accounting: a run must never fail
# because it could not explain itself.
record_reason() { printf '%s\n' "$*" >"$REASON_FILE" 2>/dev/null || true; }

abort() { record_reason "$*"; log "ABORT: $*"; exit 1; }

log "=== daily-apply run $STAMP ==="

# --- Preconditions -----------------------------------------------------------

[[ -r "$HARNESS_CLI" ]] || abort "agent harness not found: $HARNESS_CLI (build it with \`npm run build\` in agent/, or set HARNESS_CLI)"

[[ -r "$RUNBOOK" ]] || abort "runbook missing: $RUNBOOK"

[[ -n "${AGENT_API_TOKEN:-}" ]] || abort "AGENT_API_TOKEN is not set - the agent gets its LLM credentials from the app and signs in to the browser session server with it; set it in .env (see README 'Running it by hand')"

# jq builds the job-profile block of the prompt below. Without it the operator's
# configured profiles silently never reach the agent and the run proceeds on the
# RUNBOOK defaults as though none were configured - a wrong run is worse than no
# run, so this is a hard precondition, not a fallback.
command -v jq >/dev/null || abort "jq not found - the job-profile prompt block cannot be rendered (agent/Dockerfile must install it)"

# The browser is the agent's only way to apply, so an unreachable one means
# there is no point searching either. Which browser that is depends on
# AGENT_BROWSER_DRIVER, and so does the right way to check it - the two drivers
# fail differently and cannot share one probe.

# The containerised Chromium's MCP endpoint is an ordinary in-network HTTP
# server in a sibling container. Dialling it once per run is cheap and disturbs
# nothing, so the run path can check reachability for real rather than settling
# for a file-exists test.
#
# Any HTTP response at all proves the server is listening and is what we
# require here. The status code is deliberately NOT interpreted: MCP's
# streamable-HTTP transport answers a bare GET (no session, no
# `Accept: text/event-stream`) with a 4xx by design, and treating that as
# failure would abort every run against a perfectly healthy browser. A dead
# or wrong-addressed server fails as a connection error or a timeout instead.
probe_browser() {
  node -e '
    const url = process.argv[1];
    const mod = url.startsWith("https:") ? require("https") : require("http");
    const req = mod.get(url, { timeout: 5000 }, () => process.exit(0));
    req.on("timeout", () => { req.destroy(); process.exit(1); });
    req.on("error", () => process.exit(1));
  ' "$BROWSER_MCP_URL" 2>/dev/null
}

case "$AGENT_BROWSER_DRIVER" in
  browser)
    probe_browser || abort "browser MCP server unreachable at $BROWSER_MCP_URL - is the \`browser\` service up? (docker compose ps browser; docker compose logs browser)"

    # An attended sign-in session holds the same profile this run needs, so ask
    # for it back and wait out the grace period before proceeding. The session
    # server closes the session itself when its deadline passes; this loop only
    # waits for that to happen.
    #
    # Both halves of the interlock are required. session-server.js refuses to
    # OPEN a session while a run is in progress, but that is a moment-in-time
    # check — a run can start straight afterwards. Without this, both would
    # drive one profile, which is the "Browser is already in use" failure
    # browser/entrypoint.sh exists to clean up after.
    SESSION_EVICT_TIMEOUT="${SESSION_EVICT_TIMEOUT:-240}"

    session_request() {
      node -e '
        const http = require("http");
        const [method, path] = [process.argv[1], process.argv[2]];
        const req = http.request(
          { host: "browser", port: process.env.SESSION_SERVER_PORT || 8932, path, method,
            timeout: 5000, headers: { "X-Agent-Token": process.env.AGENT_API_TOKEN || "" } },
          (res) => {
            let body = "";
            res.on("data", (c) => (body += c));
            res.on("end", () => {
              // A response is not a success. The session server answers 403 to a
              // missing or mismatched X-Agent-Token — including when its own
              // AGENT_API_TOKEN is empty, which compose permits — and a 403 body
              // does not contain "open":true, so treating it as a reply would be
              // indistinguishable from "no session is open" and would silently
              // skip the eviction this interlock exists to perform.
              if (res.statusCode < 200 || res.statusCode > 299) {
                process.exit(1);
              }
              process.stdout.write(body);
              process.exit(0);
            });
          }
        );
        req.on("timeout", () => { req.destroy(); process.exit(1); });
        req.on("error", () => process.exit(1));
        req.end(method === "POST" ? "{}" : undefined);
      ' "$1" "$2" 2>/dev/null
    }

    wait_for_session_release() {
      local waited=0
      while (( waited < SESSION_EVICT_TIMEOUT )); do
        local state
        state="$(session_request GET /session)" || return 1
        if ! grep -q '"open":true' <<<"$state"; then
          return 0
        fi
        # Re-issue the eviction on every pass, not once before the loop. A
        # session in its reservation window (open() has taken the slot but the
        # browser has not launched yet) reports open:true while refusing the
        # evict, so a single request can be dropped and the run would then wait
        # out the whole timeout and abort. session-server.js also carries a
        # pending-evict flag across that window; this is the other half, and it
        # heals any refusal that flag does not cover. evict() never extends an
        # existing deadline, so repeating it cannot push the browser further
        # out of the run's reach.
        session_request POST /session/evict >/dev/null || return 1
        sleep 5
        waited=$((waited + 5))
      done
      return 2
    }

    session_state="$(session_request GET /session)" \
      || abort "session server unreachable at browser:${SESSION_SERVER_PORT:-8932} - cannot tell whether a sign-in session holds the browser (unreachable, or rejected the agent's X-Agent-Token — check AGENT_API_TOKEN matches in the agent and browser services) (docker compose logs browser)"

    if grep -q '"open":true' <<<"$session_state"; then
      log "an attended sign-in session is open - requesting the browser back"
      session_request POST /session/evict >/dev/null \
        || abort "session server unreachable while evicting the sign-in session"
      wait_for_session_release
      case $? in
        0) log "sign-in session released the browser" ;;
        1) abort "session server unreachable while waiting for the sign-in session to close" ;;
        2) abort "sign-in session did not release the browser within ${SESSION_EVICT_TIMEOUT}s" ;;
      esac
    fi
    ;;

  *)
    # Fail closed rather than silently granting no browser tools at all: an
    # unattended run that cannot apply to anything should say why, not spend an
    # LLM budget searching and then quietly skip every posting it finds.
    abort "unknown AGENT_BROWSER_DRIVER '$AGENT_BROWSER_DRIVER' - expected 'browser'"
    ;;
esac

[[ -n "${TRUTHCV_MCP_URL:-}" ]] || abort "TRUTHCV_MCP_URL is not set - it is the agent's only route to the TruthCV tools"

log "preconditions OK"

# --- Agent mode gate ----------------------------------------------------------
# The Agents page sets the agent's autonomy mode; the flag lives in the app
# service's agent config (GET /api/agent/config). Unreachable config fails
# CLOSED: if the app is down, the MCP tools this run depends on are down too,
# and "did not run" is the safe failure for an unattended submitter that
# applies to real jobs under a real person's name.
#
#   off  - exit before the model is invoked at all
#   semi - discover and screen, queue what passes for the operator, apply only
#          to what the operator already approved
#   full - discover, screen and apply, the pre-mode behaviour
AGENT_MODE="$(node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" mode)" || AGENT_MODE=""
if [[ "$AGENT_MODE" == "off" ]]; then
  record_reason "the agent is switched off on the Agents page - nothing was searched or submitted"
  log "agent mode is off - skipping run"
  exit 0
elif [[ "$AGENT_MODE" != "semi" && "$AGENT_MODE" != "full" ]]; then
  abort "agent config unreachable or mode unrecognised ('$AGENT_MODE') - skipping run (fail closed)"
fi
log "agent mode: $AGENT_MODE"

# --- Run ---------------------------------------------------------------------

# jq program rendering one criteria block per ENABLED configured profile:
# name, employment country, remote model, salary band (in the profile's own
# currency), Glassdoor minimum, EOR/entity-verification flags, working
# language, and accepted/rejected role types. Missing fields render as
# "not configured" rather than being silently dropped, so the agent never
# mistakes an unset criterion for a waived one.
# The `select(.enabled == true)` filter matches agentconfig/dorks.compose_queries:
# a disabled profile's criteria must never render into the run prompt as if
# active, since record_screening's `profile` argument only accepts an
# enabled profile name — rendering a disabled one here would offer the agent
# criteria it can never successfully screen against.
# Field names are camelCase to match the wire format api/schemas.py's
# AgentConfigModel/JobProfileModel produce (same convention as the
# targetCompanies/companyBoards/cooldownDays fields already used above).
# currency is exposed on the wire (api/schemas.py JobProfileModel) and may be
# null: no regional default exists, so a band without a configured currency
# renders as "not configured" rather than quoting a currency the user never
# chose.
PROFILE_CRITERIA_JQ='
def fmt_bool: if . == null then "not configured" elif . then "true" else "false" end;
def fmt_list: if (. // []) | length > 0 then (. // [] | join(", ")) else "not configured" end;
def fmt_band(min_v; max_v; cur): if (min_v != null and max_v != null and cur != null) then "\(min_v) - \(max_v) \(cur)" else "not configured" end;
.profiles[] | select(.enabled == true) |
"### Profile: \(.name)\n" +
"  - Employment country: \(.employmentCountry // "not configured")\n" +
"  - Remote model: \(.remoteModel // "not configured")\n" +
"  - Salary band: \(fmt_band(.salaryAskMin; .salaryAskMax; .currency))\n" +
"  - Glassdoor min rating: \(.glassdoorMin // "not configured")\n" +
"  - EOR allowed: \(.eorAllowed | fmt_bool)\n" +
"  - Entity verification required: \(.requireEntityVerification | fmt_bool)\n" +
"  - Working language: \(.workingLanguage // "not configured")\n" +
"  - Accepted role types: \(.acceptedRoleTypes | fmt_list)\n" +
"  - Rejected role types: \(.rejectedRoleTypes | fmt_list)\n" +
"  - ENFORCED at record_screening time (not advisory): the remote model and\n" +
"    working language above are checked against the posting'"'"'s stated evidence;\n" +
"    a contradiction auto-downgrades the record to verdict=\"rejected\".\n"
'

# Job profiles: the run's search criteria. The agent has no built-in policy:
# without at least one enabled profile there is nothing to search for, so the
# run aborts before invoking the LLM instead of silently applying someone
# else's defaults.
if JOB_CONFIG="$(node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" job_config 2>/dev/null)"; then
  # Parse check first: a payload that is not JSON at all (a truncated or
  # corrupt fetch) must be reported as such, not as a profiles problem — the
  # shape check below cannot tell the two apart.
  if ! jq -e . <<<"$JOB_CONFIG" >/dev/null 2>&1; then
    abort "Agent config payload was not valid JSON (fetch was truncated or corrupt; ${#JOB_CONFIG} characters received) - check the app service log and rerun"
  fi
  # A malformed payload must not read as "zero profiles configured": that
  # message sends the operator to add profiles they already have. Probe the
  # payload's shape next (the parse check above has already run, so a
  # truncated payload is no longer reported as a profiles problem), so a
  # broken config gets its own diagnosis. The every() guard catches
  # non-object elements, which jq would otherwise skip silently (or error on,
  # depending on version).
  if ! jq -e '.profiles // [] | (type == "array") and all(.[]; type == "object" or . == null)' <<<"$JOB_CONFIG" >/dev/null; then
    abort "Agent config fetched but is malformed (.profiles is missing, not an array, or contains non-object entries) - fix data/agent_config.json or the Agents page before the agent can run"
  fi
  ENABLED_PROFILES="$(jq -r '[.profiles // [] | .[] | select((type == "object") and (.enabled == true))] | length' <<<"$JOB_CONFIG")"
  if [[ "$ENABLED_PROFILES" -eq 0 ]]; then
    abort "No enabled job profiles configured — set your search criteria on the Agents page before the agent can run (config fetch succeeded; it contained zero enabled profiles)"
  fi
fi

# Per-run application cap: the Agents page's maxApplicationsPerRun (fetched
# above in JOB_CONFIG) is the source of truth; MAX_APPLICATIONS_PER_RUN is the
# fallback, used only when the config is unreachable (JOB_CONFIG empty — the
# zero-enabled-profiles case aborted above) or does not set the field - the
# same config-first/env-fallback precedence agent/entrypoint.sh and
# agent/supervisor.js already use for RUN_AT/RUN_DAYS.
CONFIG_CAP=""
if [[ -n "$JOB_CONFIG" ]]; then
  # No stderr suppression, matching the jq calls above: jq is a checked
  # precondition, so a jq failure here means malformed config and must be
  # visible in the run log. `.maxApplicationsPerRun` renders as the literal
  # string "null" when the field is JSON null, which the regex below rejects
  # same as any other non-positive-integer value.
  CONFIG_CAP="$(jq -r '.maxApplicationsPerRun' <<<"$JOB_CONFIG")"
fi
if [[ "$CONFIG_CAP" =~ ^[1-9][0-9]*$ ]]; then
  APPLY_CAP="$CONFIG_CAP"
else
  APPLY_CAP="${MAX_APPLICATIONS_PER_RUN:-}"
fi
# Empty/unset (from either source) means no cap (agent/RUNBOOK.md §1, "there
# is no daily quota"; docker-compose.yml defaults the env var to empty for
# that reason). Only a positive integer is enforced (pipeline apply loop).

# Fetch routed LLM credentials from the app (Stage 2) and export them as the
# provider-neutral variables the harness consumes (AGENT_LLM_*).
AGENT_MODEL=""
if CREDS="$(node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" llm_credentials 2>/dev/null)"; then
  # Six lines, in order: authType, token, model, baseUrl, provider, wire.
  # An older agent-config.js emitting fewer lines yields empty values for
  # the missing ones here (sed on a missing line prints nothing), which the
  # final gate rejects for the required fields.
  AUTH_TYPE="$(sed -n 1p <<<"$CREDS")"
  AUTH_TOKEN="$(sed -n 2p <<<"$CREDS")"
  AGENT_MODEL="$(sed -n 3p <<<"$CREDS")"
  AGENT_BASE_URL="$(sed -n 4p <<<"$CREDS")"
  AGENT_PROVIDER="$(sed -n 5p <<<"$CREDS")"
  AGENT_WIRE="$(sed -n 6p <<<"$CREDS")"

  export AGENT_LLM_PROVIDER="$AGENT_PROVIDER"
  export AGENT_LLM_MODEL="$AGENT_MODEL"
  # Empty token is valid for ollama; the final gate enforces the per-provider
  # rule, so we do not reject an empty token unconditionally here.
  export AGENT_LLM_API_KEY="$AUTH_TOKEN"
  export AGENT_LLM_BASE_URL="$AGENT_BASE_URL"
  export AGENT_LLM_WIRE="$AGENT_WIRE"
  # Distinct from AGENT_LLM_PROVIDER: a claude connection can be either
  # 'oauth' or 'api_key', and the harness must send the token via the
  # matching wire mechanism (Bearer vs x-api-key) or an oauth token is
  # rejected when sent as an api key. Forwarded verbatim to the harness CLI.
  export AGENT_LLM_AUTH_TYPE="$AUTH_TYPE"
  log "using ${AGENT_LLM_PROVIDER:-unknown} credentials from app${AGENT_LLM_BASE_URL:+ ($AGENT_LLM_BASE_URL)}"
  unset CREDS AUTH_TOKEN AUTH_TYPE AGENT_PROVIDER AGENT_WIRE
else
  abort "credential fetch failed (app returned non-zero exit)"
fi

# Per-stage routes (llm_routes) go to a 0600 temp file, removed on exit; the
# token never reaches argv or the log.
ROUTES_FILE=""
PIPE_DIR=""
cleanup_tmp() { [[ -n "$ROUTES_FILE" ]] && rm -f "$ROUTES_FILE"; [[ -n "$PIPE_DIR" ]] && rm -rf "$PIPE_DIR"; return 0; }
trap cleanup_tmp EXIT
ROUTES_FILE="$(umask 077; mktemp)"
if ! node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" llm_routes >"$ROUTES_FILE" 2>/dev/null; then
  rm -f "$ROUTES_FILE"; ROUTES_FILE=""
fi

# Final gate: the harness needs a known provider AND a usable credential for it.
# claude|codex|openrouter each require a non-empty token; ollama legitimately
# has none and requires a base URL instead.
case "$AGENT_LLM_PROVIDER" in
  claude|codex|openrouter)
    [[ -n "$AGENT_LLM_API_KEY" ]] || abort "no usable LLM credential for provider '$AGENT_LLM_PROVIDER': save a credential for the Application agent route on the Model routing page"
    ;;
  ollama)
    [[ -n "$AGENT_LLM_BASE_URL" ]] || abort "provider 'ollama' requires a base URL: set the Ollama connection's base URL on the Model routing page"
    ;;
  *)
    abort "unrecognised or unset LLM provider '$AGENT_LLM_PROVIDER' (expected claude|codex|openrouter|ollama)"
    ;;
esac

# AGENT_LLM_WIRE must be set to one of the three known values — an empty or
# unknown wire would silently fall through to the wrong adapter (the harness
# only recently stopped doing that) and would send an OAuth token as an API
# key against the wrong endpoint. Fail loudly, same style as the provider
# gate above.
case "${AGENT_LLM_WIRE:-}" in
  anthropic-messages|openai-chat-completions|openai-responses) ;;
  *)
    abort "unrecognised or unset LLM wire '${AGENT_LLM_WIRE:-}' (expected anthropic-messages|openai-chat-completions|openai-responses)"
    ;;
esac

# The tool allow-list is NOT passed on the command line any more: it is
# hardcoded inside the harness (agent/harness/tools.ts), which enforces the
# tool allow-list itself — the same 19 named truthcv tools granted
# individually (generate_cover_letter, record_application, record_screening,
# check_cooldown, get_canonical_cv, get_profile_answers, record_company_board,
# get_job_profiles, recommend_salary, get_approved_applications,
# report_apply_failure, record_company_finding, get_company_findings, start_run,
# finish_run, record_run_note, record_postings_seen, record_discovery_coverage,
# check_gmail_responses),
# plus an enumerated allow-list of browser server tools (BROWSER_ALLOWED_TOOL_NAMES in
# agent/harness/tools.ts, mirrored in mcp.json's browser.allowedTools) — only
# the tool names this RUNBOOK actually calls, not the whole upstream
# @playwright/mcp server; the harness fails loudly at startup if one of those
# names is missing from what the browser server advertises. Naming each tool
# keeps the blast radius of a new server-side tool at zero until it is granted
# on purpose. Read/Write/WebSearch/WebFetch are gone entirely: the harness's
# only non-MCP tool is read_runbook_section, which returns one named section
# of RUNBOOK.md and takes no path argument (no general filesystem read).

# This is an unattended run with stdin at /dev/null, so it cannot block on any
# approval prompt — the harness's hardcoded allow-list, not an interactive
# prompt, is the authorization boundary. The composed prompt (with the
# RUNBOOK's non-negotiable rules and a table of contents, not the whole file
# — see above) is handed over via a temp file.
log "invoking agent harness... (provider: $AGENT_LLM_PROVIDER, browser driver: $AGENT_BROWSER_DRIVER)"

# The harness writes its final assistant message here; named alongside RUN_LOG
# so a run's artifacts share one stamp+id prefix.
RUN_OUTPUT="$RUN_LOG_DIR/run_${STAMP}_${TRUTHCV_RUN_ID}.output"
# Dedicated metadata-only stream; never interpolate an unsafe id into its path.
DIAGNOSTIC_FILE=""
if [[ "$TRUTHCV_RUN_ID" =~ ^[a-zA-Z0-9_-]{1,80}$ ]]; then
  DIAGNOSTIC_FILE="$RUN_LOG_DIR/diagnostics_${TRUTHCV_RUN_ID}.ndjson"
fi

# Exit codes are the harness's machine contract: 0 success, 2 turn cap, 3
# provider error, 4 MCP connection failure, 5 bad configuration, 6 the agent
# ended cleanly without calling finish_run. They are logged and propagated
# verbatim below, not remapped.
#
# The --screening-* flags configure the screen_posting built-in's own,
# separate provider adapter (agent/harness/builtins/screenPosting.ts). Each
# defaults, at the shell level, to the SAME value as its main-model
# equivalent above (AGENT_SCREENING_MODEL falling back to $AGENT_MODEL, and
# so on) — so an operator who sets no AGENT_SCREENING_* container env var
# gets today's exact behaviour: one model doing both jobs. Set the
# AGENT_SCREENING_* env vars to point screening at a separate, cheaper model
# instead.
# run_harness takes the prompt file and finish-tool name as arguments so the
# pipeline can invoke it once per apply session, each with its own prompt
# and --finish-tool (finish_application).
run_harness() {
local prompt_file="$1" finish_tool="$2" system_prompt_file="${3:-}"
local extra=()
[[ -n "$ROUTES_FILE" ]] && extra+=(--routes-file "$ROUTES_FILE")
[[ -n "$system_prompt_file" ]] && extra+=(--system-prompt-file "$system_prompt_file")
[[ -n "${AGENT_SCREENING_MODEL:-}" ]] && extra+=(--screening-model "$AGENT_SCREENING_MODEL")
[[ -n "${AGENT_SCREENING_PROVIDER:-}" ]] && extra+=(--screening-provider "$AGENT_SCREENING_PROVIDER")
[[ -n "${AGENT_SCREENING_WIRE:-}" ]] && extra+=(--screening-wire "$AGENT_SCREENING_WIRE")
[[ -n "${AGENT_SCREENING_API_KEY:-}" ]] && extra+=(--screening-token "$AGENT_SCREENING_API_KEY")
[[ -n "${AGENT_SCREENING_BASE_URL:-}" ]] && extra+=(--screening-base-url "$AGENT_SCREENING_BASE_URL")
[[ -n "${AGENT_SCREENING_AUTH_TYPE:-}" ]] && extra+=(--screening-auth-type "$AGENT_SCREENING_AUTH_TYPE")
node "$HARNESS_CLI" \
  "${extra[@]}" \
  --prompt-file "$prompt_file" \
  --model "$AGENT_MODEL" \
  --provider "$AGENT_LLM_PROVIDER" \
  --wire "$AGENT_LLM_WIRE" \
  --auth-type "$AGENT_LLM_AUTH_TYPE" \
  --token "$AGENT_LLM_API_KEY" \
  --base-url "$AGENT_LLM_BASE_URL" \
  --mcp-config "$MCP_CONFIG" \
  --max-turns "${AGENT_MAX_TURNS:-400}" \
  --max-retries "${AGENT_MAX_RETRIES:-12}" \
  --max-retry-delay-ms "${AGENT_MAX_RETRY_DELAY_MS:-300000}" \
  --max-tool-result-chars "${AGENT_MAX_TOOL_RESULT_CHARS:-24000}" \
  --prompt-cache "${AGENT_PROMPT_CACHE:-true}" \
  --finish-tool "$finish_tool" \
  --output-file "$RUN_OUTPUT" \
  --reason-file "$REASON_FILE" \
  --diagnostics-file "$DIAGNOSTIC_FILE" \
  --run-id "$TRUTHCV_RUN_ID" \
  </dev/null >>"$RUN_LOG" 2>&1
}

# Renders 'Applications remaining this run: N' from the run record's live
# applications_submitted (GET /api/runs/{run_id}, same base URL as
# TRUTHCV_MCP_URL with /mcp stripped, no auth required — the same route the
# web UI reads). Falls back to the static cap line on any fetch failure
# (run not yet recorded, network error, malformed body) so an
# apply session never blocks on this becoming available.
render_remaining_line() {
  local cap="$1"
  [[ "$cap" =~ ^[1-9][0-9]*$ ]] || { printf ''; return; }
  local base="${TRUTHCV_MCP_URL%/mcp}"
  base="${base%/mcp/}"
  local submitted
  submitted="$(node -e '
const http = require("http"); const https = require("https");
let u;
try { u = new URL(process.argv[1] + "/api/runs/" + process.argv[2]); } catch { process.exit(1); }
const mod = u.protocol === "https:" ? https : http;
const req = mod.get(u, { timeout: 5000 }, (res) => {
  if (res.statusCode !== 200) { res.resume(); process.exit(1); }
  let body = "";
  res.on("data", (c) => (body += c));
  res.on("end", () => {
    try {
      const rec = JSON.parse(body);
      const submittedRaw = rec.applicationsSubmitted !== undefined ? rec.applicationsSubmitted : rec.applications_submitted;
      const n = Number(submittedRaw);
      if (!Number.isFinite(n)) process.exit(1);
      process.stdout.write(String(n));
    } catch { process.exit(1); }
  });
});
req.on("timeout", () => { req.destroy(); process.exit(1); });
req.on("error", () => process.exit(1));
' "$base" "$TRUTHCV_RUN_ID" 2>/dev/null)" || submitted=""
  if [[ "$submitted" =~ ^[0-9]+$ ]]; then
    local remaining=$(( cap - submitted ))
    (( remaining < 0 )) && remaining=0
    printf 'Applications remaining this run: %s' "$remaining"
  else
    printf 'Apply to at most %s role(s) this run.' "$cap"
  fi
}

FD3_OPEN=0
if [[ "${TRUTHCV_DIAGNOSTICS_FD:-}" == 3 && -e /dev/fd/3 ]]; then
  FD3_OPEN=1
else
  unset TRUTHCV_DIAGNOSTICS_FD
fi

FINAL_RC=0
FINAL_RC_SET=0

# Pipeline: code discovers and screens; apply sessions only apply. A failed
# apply session for one posting (rc 1/2/6) is a per-item failure: it is logged
# to APPLY_FAILURES_FILE and counted by `finish`, never failing the run. rc
# 3/4/5 (provider/MCP/config) are systemic and stop the apply loop.
PIPELINE_CLI="${PIPELINE_CLI:-/app/agent/dist/harness/pipeline/pipelineCli.js}"
PIPE_DIR="$(umask 077; mktemp -d)"
PIPE_ISSUES=""
PIPE_FLAGS=(--mcp-config "$MCP_CONFIG" --run-id "$TRUTHCV_RUN_ID")
[[ -n "$ROUTES_FILE" ]] && PIPE_FLAGS+=(--routes-file "$ROUTES_FILE")
# start/finish need no model: no credentials at all. Only discover-screen
# (pipe_cli_model) gets them, through the environment - never argv.
pipe_cli() {
  node "$PIPELINE_CLI" "$@" "${PIPE_FLAGS[@]}" </dev/null >>"$RUN_LOG" 2>&1
}
pipe_cli_model() {
  AGENT_LLM_MODEL="$AGENT_MODEL" AGENT_LLM_PROVIDER="$AGENT_LLM_PROVIDER" AGENT_LLM_WIRE="$AGENT_LLM_WIRE" \
    AGENT_LLM_AUTH_TYPE="$AGENT_LLM_AUTH_TYPE" AGENT_LLM_API_KEY="$AGENT_LLM_API_KEY" AGENT_LLM_BASE_URL="$AGENT_LLM_BASE_URL" \
    pipe_cli "$@"
}
START_ARGS=(start --out "$PIPE_DIR/approved.json")
[[ "$APPLY_CAP" =~ ^[1-9][0-9]*$ ]] && START_ARGS+=(--limit "$APPLY_CAP")
note_rc() { # name rc: record the first failure and any non-zero rc
  (( $2 == 0 )) && return 0
  PIPE_ISSUES="${PIPE_ISSUES:+$PIPE_ISSUES | }$1 rc=$2"
  if (( FINAL_RC_SET == 0 )); then FINAL_RC=$2; FINAL_RC_SET=1; fi
  if [[ -z "$FIRST_FAILURE_REASON" ]]; then FIRST_FAILURE_REASON="$(cat "$REASON_FILE" 2>/dev/null || true)"; fi
}
FIRST_FAILURE_REASON=""
APPROVED_FILE="$PIPE_DIR/approved.json"; PASSES_FILE="$PIPE_DIR/passes.json"
CRITERIA_FILE="$PIPE_DIR/criteria.json"; JOB_FILE="$PIPE_DIR/job.json"
SYSTEM_FILE="$PIPE_DIR/apply-system.txt"
APPLY_FAILURES_FILE="$PIPE_DIR/apply-failures.txt"
pipe_cli "${START_ARGS[@]}"; note_rc start $?
if (( FINAL_RC == 0 )); then
  printf '%s' "$JOB_CONFIG" >"$JOB_FILE"
  NAMES_JSON="$(jq -c '[.profiles[] | select(.enabled == true) | .name]' <<<"$JOB_CONFIG")"
  TEXTS_JSON="$(jq -c "[$PROFILE_CRITERIA_JQ]" <<<"$JOB_CONFIG")"
  jq -n --argjson n "$NAMES_JSON" --argjson t "$TEXTS_JSON" '[range(0; $n|length) | {key: $n[.], value: $t[.]}] | from_entries' >"$CRITERIA_FILE"
  pipe_cli_model discover-screen --job-config "$JOB_FILE" --criteria "$CRITERIA_FILE" --out "$PASSES_FILE" --dork-state-file "$RUN_LOG_DIR/dork-state.json"; note_rc discover-screen $?
  node "$PIPELINE_CLI" stage-prompt apply >"$SYSTEM_FILE" 2>>"$RUN_LOG"; note_rc stage-prompt $?
fi
if (( FINAL_RC == 0 || FINAL_RC == 3 )) && [[ -s "$SYSTEM_FILE" ]]; then
  APPLY_ITEMS=()
  if [[ -s "$APPROVED_FILE" ]]; then
    while IFS= read -r ITEM; do [[ -n "$ITEM" ]] && APPLY_ITEMS+=("approved:$ITEM"); done < <(jq -c '(if type == "array" then .[] else ((.applications // .approved // [])[]) end) | select((.blocked_reason // "") == "")' "$APPROVED_FILE" 2>/dev/null)
  fi
  # Semi-auto leaves new passes for operator approval; only full auto applies to them.
  if [[ "$AGENT_MODE" == "full" && -s "$PASSES_FILE" ]]; then
    while IFS= read -r ITEM; do [[ -n "$ITEM" ]] && APPLY_ITEMS+=("pass:$ITEM"); done < <(jq -c '.passes[]?' "$PASSES_FILE" 2>/dev/null)
  fi
  LAUNCHED=0 # local budget: a failed run-count read must never exceed the cap
  for ENTRY in "${APPLY_ITEMS[@]:-}"; do
    [[ -z "$ENTRY" ]] && continue
    if [[ "$APPLY_CAP" =~ ^[1-9][0-9]*$ ]] && (( LAUNCHED >= APPLY_CAP )); then break; fi
    KIND="${ENTRY%%:*}"; POSTING="${ENTRY#*:}"
    REMAINING_LINE="$(render_remaining_line "$APPLY_CAP")"
    if [[ "$KIND" == pass && "$APPLY_CAP" =~ ^[1-9][0-9]*$ && "$REMAINING_LINE" == *"remaining this run: 0" ]]; then break; fi
    POSTING_PROMPT_FILE="$(mktemp "$PIPE_DIR/posting.XXXXXX")"
    printf 'Date: %s\nRun id: %s\nKind: %s\nPosting: %s\n%s\n' "$(date +%Y-%m-%d)" "$TRUTHCV_RUN_ID" "$KIND" "$POSTING" "$REMAINING_LINE" >"$POSTING_PROMPT_FILE"
    LAUNCHED=$((LAUNCHED + 1))
    log "session start: apply posting ($KIND)"
    rm -f "$REASON_FILE" 2>/dev/null || true # a session that writes no reason must not reuse the last one
    run_harness "$POSTING_PROMPT_FILE" finish_application "$SYSTEM_FILE"
    SESSION_RC=$?
    log "session end: apply rc=$SESSION_RC"
    if [[ "$SESSION_RC" == 3 || "$SESSION_RC" == 4 || "$SESSION_RC" == 5 ]]; then
      note_rc apply "$SESSION_RC"
      break
    elif (( SESSION_RC != 0 )); then
      # Per-item failure (1 other, 2 turn cap, 6 no finish call): counted, not fatal.
      ITEM_URL="$(jq -r '.url // empty' <<<"$POSTING" 2>/dev/null || true)"
      ITEM_REASON="$(tr '\r\n' '  ' <"$REASON_FILE" 2>/dev/null || true)"
      APPLY_FAILURE="apply $KIND ${ITEM_URL:-$POSTING} rc=$SESSION_RC: $ITEM_REASON"
      APPLY_FAILURE="$(tr '\r\n' '  ' <<<"$APPLY_FAILURE")"
      printf '%s\n' "$APPLY_FAILURE" >>"$APPLY_FAILURES_FILE"
      log "apply failure (per-item): $APPLY_FAILURE"
    fi
  done
fi
FINISH_ARGS=(finish --issues "$PIPE_ISSUES")
[[ -s "$PASSES_FILE" ]] && FINISH_ARGS+=(--state-file "$PASSES_FILE")
[[ -s "$APPLY_FAILURES_FILE" ]] && FINISH_ARGS+=(--apply-failures-file "$APPLY_FAILURES_FILE")
pipe_cli "${FINISH_ARGS[@]}"; FINISH_RC=$?
(( FINAL_RC == 0 && FINISH_RC != 0 )) && FINAL_RC=$FINISH_RC
if [[ -n "$FIRST_FAILURE_REASON" ]]; then
  printf '%s\n' "$FIRST_FAILURE_REASON" >"$REASON_FILE" 2>/dev/null || true
elif (( FINAL_RC == 0 )); then
  # A per-item apply failure's reason is in the counted failures, not the run's stopped_reason.
  rm -f "$REASON_FILE" 2>/dev/null || true
fi

if (( FD3_OPEN )); then
  exec 3>&-
fi

RC=$FINAL_RC
log "agent harness exited rc=$RC"

log "=== run complete: $RUN_LOG ==="
exit $RC
