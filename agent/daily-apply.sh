#!/usr/bin/env bash
# Daily job-application run for TruthCV's unattended agent (agent/Dockerfile,
# docker-compose.yml `agent` service, plan agent-container-and-schedule task
# t-2). Ported from the retiring Jobs project's bin/daily-apply.sh, moved off
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
# The containerised Chromium's MCP endpoint (docker-compose.yml `browser`
# service, browser/Dockerfile). Same default as agent/mcp.json's
# ${BROWSER_MCP_URL:-...} expansion, so the probe below and the server the
# claude CLI actually dials cannot drift apart.
BROWSER_MCP_URL="${BROWSER_MCP_URL:-http://browser:8931/mcp}"
STAMP="$(date +%Y-%m-%d_%H%M)"

mkdir -p "$RUN_LOG_DIR"
RUN_LOG="$RUN_LOG_DIR/run_$STAMP.log"

log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$RUN_LOG"; }

abort() { log "ABORT: $*"; exit 1; }

log "=== daily-apply run $STAMP ==="

# --- Preconditions -----------------------------------------------------------

CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude)}"
[[ -n "$CLAUDE_BIN" && -x "$CLAUDE_BIN" ]] || abort "claude CLI not found (set CLAUDE_BIN, or put claude on PATH)"

[[ -r "$RUNBOOK" ]] || abort "runbook missing: $RUNBOOK"

# jq builds the job-profile block of the prompt below. Without it the operator's
# configured profiles silently never reach the agent and the run proceeds on the
# RUNBOOK defaults as though none were configured - a wrong run is worse than no
# run, so this is a hard precondition, not a fallback.
command -v jq >/dev/null || abort "jq not found - the job-profile prompt block cannot be rendered (agent/Dockerfile must install it)"

# The browser is the agent's only way to apply, so an unreachable one means
# there is no point searching either. Unlike the retired host-socket design -
# where probing meant opening and dropping a connection on the operator's own
# live browser daemon, and so had to be left to the deliberate smoke test -
# this is an ordinary in-network HTTP server in a sibling container. Dialling
# it once per run is cheap and disturbs nothing, so the run path can check
# reachability for real rather than settling for a file-exists test.
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
probe_browser || abort "browser MCP server unreachable at $BROWSER_MCP_URL - is the \`browser\` service up? (docker compose ps browser; docker compose logs browser)"

[[ -n "${TRUTHCV_MCP_URL:-}" ]] || abort "TRUTHCV_MCP_URL is not set - it is the agent's only route to the TruthCV tools"

log "preconditions OK"

# --- Agent enable gate --------------------------------------------------------
# The Agents page can switch the agent off; the flag lives in the app service's
# agent config (GET /api/agent/config). Unreachable config fails CLOSED: if the
# app is down, the MCP tools this run depends on are down too, and "did not
# run" is the safe failure for an unattended submitter.
ENABLED="$(node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" enabled)" || ENABLED=""
if [[ "$ENABLED" == "false" ]]; then
  log "agent disabled in config - skipping run"
  exit 0
elif [[ "$ENABLED" != "true" ]]; then
  abort "agent config unreachable - skipping run (fail closed)"
fi

# --- Run ---------------------------------------------------------------------

# agent/prompt.md carries the operating instructions (it references
# agent/RUNBOOK.md and names the nine tools); this script only adds the date.
PROMPT="$(cat "$PROMPT_FILE")"$'\n\n'"Today is $(date +%Y-%m-%d)."

# MAX_APPLICATIONS_PER_RUN empty/unset means no cap (agent/RUNBOOK.md §1,
# "there is no daily quota"; docker-compose.yml defaults it to empty for that
# reason). Only append a limit line when it is actually a positive integer,
# so the common empty case adds nothing to the prompt.
if [[ "${MAX_APPLICATIONS_PER_RUN:-}" =~ ^[1-9][0-9]*$ ]]; then
  PROMPT="$PROMPT"$'\n\n'"Apply to at most $MAX_APPLICATIONS_PER_RUN role(s) this run."
fi

# jq program rendering one criteria block per configured profile: name,
# employment country, remote model, salary band (in the profile's own
# currency), Glassdoor minimum, EOR/entity-verification flags, working
# language, and accepted/rejected role types. Missing fields render as
# "not configured" rather than being silently dropped, so the agent never
# mistakes an unset criterion for a waived one.
# Field names are camelCase to match the wire format api/schemas.py's
# AgentConfigModel/JobProfileModel produce (same convention as the
# targetCompanies/companyBoards/cooldownDays fields already used above).
# currency is exposed on the wire (api/schemas.py JobProfileModel) and
# defaults to "EUR"; the jq fallback repeats that default so an older
# config payload without the field still renders a band.
PROFILE_CRITERIA_JQ='
def fmt_bool: if . == null then "not configured" elif . then "true" else "false" end;
def fmt_list: if (. // []) | length > 0 then (. // [] | join(", ")) else "not configured" end;
def fmt_band(min_v; max_v; cur): if (min_v != null and max_v != null) then "\(min_v) - \(max_v) \(cur // "EUR")" else "not configured" end;
.profiles[] |
"### Profile: \(.name)\n" +
"  - Employment country: \(.employmentCountry // "not configured")\n" +
"  - Remote model: \(.remoteModel // "not configured")\n" +
"  - Salary band: \(fmt_band(.salaryAskMin; .salaryAskMax; .currency))\n" +
"  - Glassdoor min rating: \(.glassdoorMin // "not configured")\n" +
"  - EOR allowed: \(.eorAllowed | fmt_bool)\n" +
"  - Entity verification required: \(.requireEntityVerification | fmt_bool)\n" +
"  - Working language: \(.workingLanguage // "not configured")\n" +
"  - Accepted role types: \(.acceptedRoleTypes | fmt_list)\n" +
"  - Rejected role types: \(.rejectedRoleTypes | fmt_list)\n"
'

# Job profiles: when configured, append search strategies and requirements.
# Fetch from the agent config endpoint (profiles, target_companies, cooldown_days,
# maxApplicationsPerRun, companyBoards). If fetch fails or profiles are absent,
# prompt stays unchanged (§2 default: the six RUNBOOK.md filters apply).
if JOB_CONFIG="$(node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" job_config 2>/dev/null)"; then
  # No `|| echo 0` and no stderr suppression on the jq calls in this block: jq is
  # a checked precondition above, so a jq failure here means malformed config,
  # not a missing tool - and it must be visible in the run log rather than
  # quietly collapsing to "no profiles configured".
  PROFILES="$(jq -r '.profiles // [] | length' <<<"$JOB_CONFIG")"
  if [[ "$PROFILES" -gt 0 ]]; then
    # Append a block for each enabled profile
    PROFILE_BLOCK="## Job profiles configured:"$'\n'
    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Any profile passing all its criteria drives an application (single-profile-passes rule)."$'\n'
    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Record which profile drove each application in the screening report."$'\n'
    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Target companies (watchlist): $(jq -r '.targetCompanies | join(", ")' <<<"$JOB_CONFIG")"$'\n'
    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Resolved company boards and apply-channel URLs:"$'\n'
    
    # Add company boards (resolved)
    BOARDS="$(jq -r '.companyBoards[]? | "\(.company): \(.careersUrl)"' <<<"$JOB_CONFIG" | sed 's/^/  - /')"
    if [[ -n "$BOARDS" ]]; then
      PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"$BOARDS"$'\n'
    fi
    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Cooldown days (stale company filter): $(jq -r '.cooldownDays // "not configured"' <<<"$JOB_CONFIG")"$'\n'

    # Render each profile's full criteria: name, employment country, remote
    # model, salary band, Glassdoor minimum, EOR/entity-verification rules,
    # working language, and accepted/rejected role types. The agent matches
    # each posting against these instead of the RUNBOOK.md §2 defaults, and
    # must quote the matched profile's name back with get_job_profiles /
    # recommend_salary.
    PROFILE_CRITERIA="$(jq -r "$PROFILE_CRITERIA_JQ" <<<"$JOB_CONFIG")"
    if [[ -n "$PROFILE_CRITERIA" ]]; then
      PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Profile criteria (call get_job_profiles to re-fetch verbatim; call"$'\n'"recommend_salary with the matched profile's name for any salary-expectation field):"$'\n\n'"$PROFILE_CRITERIA"$'\n'
    fi

    PROMPT="$PROMPT"$'\n\n'"$PROFILE_BLOCK"
  fi
fi

# Fetch routed LLM credentials from the app (Stage 2). Fallback: the
# container's ANTHROPIC_API_KEY env, exactly the pre-Stage-2 behavior.
AGENT_MODEL=""
if [[ -n "${AGENT_API_TOKEN:-}" ]]; then
  if CREDS="$(node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" llm_credentials 2>/dev/null)"; then
    AUTH_TYPE="$(sed -n 1p <<<"$CREDS")"
    AUTH_TOKEN="$(sed -n 2p <<<"$CREDS")"
    AGENT_MODEL="$(sed -n 3p <<<"$CREDS")"
    if [[ "$AUTH_TYPE" == "oauth" ]]; then
      export CLAUDE_CODE_OAUTH_TOKEN="$AUTH_TOKEN"
      unset ANTHROPIC_API_KEY
      log "using Claude subscription credentials from app"
    elif [[ "$AUTH_TYPE" == "api_key" ]]; then
      export ANTHROPIC_API_KEY="$AUTH_TOKEN"
      log "using API key credentials from app"
    else
      abort "unrecognized auth type from app: $AUTH_TYPE (expected oauth or api_key)"
    fi
    [[ -n "$AUTH_TOKEN" ]] || abort "credential fetch returned empty token for $AUTH_TYPE"
    unset CREDS AUTH_TOKEN
  else
    abort "credential fetch failed (app returned non-zero exit)"
  fi
fi

# Final gate: at least one credential source must be set
[[ -n "${ANTHROPIC_API_KEY:-}" ]] || [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]] || abort "no usable LLM credential: set ANTHROPIC_API_KEY or AGENT_API_TOKEN + app credentials"
MODEL_ARGS=()
[[ -n "$AGENT_MODEL" ]] && MODEL_ARGS=(--model "$AGENT_MODEL")

log "invoking claude..."

# The browser is granted as the whole server, `mcp__browser`, rather than as an
# enumerated tool list. Every other grant below is a single named tool, and the
# asymmetry is deliberate: the truthcv tools are OUR nine, fixed by
# agenttools/server.py and changing only when we change it, so naming them keeps
# the blast radius of a new tool at zero until it is granted on purpose. The
# browser server is upstream @playwright/mcp (browser/Dockerfile), whose tool set
# - browser_navigate, browser_click, browser_type, browser_file_upload,
# browser_snapshot, browser_take_screenshot and the rest - is theirs to rename or
# extend on any version bump; pinning a list here would silently disable whichever
# tool got renamed, mid-run, in an unattended job. Containment for the browser
# comes from the container instead: no host filesystem, no host network, its
# profile on its own volume, and the app data volume mounted read-only.
#
# (Superseding the Jobs original's mcp__plugin_playwright_playwright__* grants,
# which were dropped when this image had no browser at all.)
#
# --dangerously-skip-permissions: this is an unattended run with stdin at
# /dev/null, so any trust or permission prompt would EOF and kill the run. The
# --allowedTools list above, not an interactive prompt, is the actual boundary on
# what the agent may do; the flag only stops the run blocking on a question no
# one is there to answer.
"$CLAUDE_BIN" -p "$PROMPT" "${MODEL_ARGS[@]}" \
  --mcp-config "$MCP_CONFIG" \
  --allowedTools \
    "Read" "Write" "WebSearch" "WebFetch" \
    "mcp__truthcv__generate_cover_letter" \
    "mcp__truthcv__record_application" \
    "mcp__truthcv__record_screening" \
    "mcp__truthcv__check_cooldown" \
    "mcp__truthcv__get_canonical_cv" \
    "mcp__truthcv__get_profile_answers" \
    "mcp__truthcv__record_company_board" \
    "mcp__truthcv__get_job_profiles" \
    "mcp__truthcv__recommend_salary" \
    "mcp__browser" \
  --dangerously-skip-permissions \
  </dev/null >>"$RUN_LOG" 2>&1

RC=$?
log "claude exited rc=$RC"

log "=== run complete: $RUN_LOG ==="
exit $RC
