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
INTERCEPTOR_SOCKET="${INTERCEPTOR_SOCKET:-/tmp/interceptor.sock}"
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

# Interceptor drives the operator's real, already-logged-in browser on the HOST over
# a unix socket bind-mounted into this container (docker-compose.yml,
# agent/mcp.json). Without it there is no way to apply, and no point
# searching.
[[ -S "$INTERCEPTOR_SOCKET" ]] || abort "interceptor socket absent: $INTERCEPTOR_SOCKET - is the interceptor daemon running on the host?"

# The Jobs original also required a live Chrome process (`pgrep -x chrome` /
# `pgrep -f google-chrome`) so interceptor had a browser on the same machine
# to attach to. That check cannot survive containerisation: this agent now
# runs in its own container while Chrome runs on the HOST, so the container's
# process table will never show it - kept unchanged it would abort every
# single run, unconditionally, which is as useless as deleting it outright.
# The honest replacement is to check that the socket is actually live
# (accepting connections), not merely a stale file left behind by an
# interceptor process that has since died. This image has no tool that can
# dial a unix socket to test that - agent/Dockerfile installs only
# ca-certificates, tzdata and the claude CLI, no nc/socat/curl - so that
# connectability probe cannot be done with those. The base image does ship
# node, which CAN dial a unix socket - agent/smoke-test.sh uses it for exactly
# this - but a probe here would open and drop a connection on the operator's
# live browser daemon before every run, so it is kept in the smoke test where
# it is run deliberately. The -S check above is therefore the only guard on the
# run path; a present-but-dead socket surfaces when the interceptor MCP server
# fails to respond mid-run.

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
  PROFILES="$(jq -r '.profiles // [] | length' <<<"$JOB_CONFIG" 2>/dev/null || echo 0)"
  if [[ "$PROFILES" -gt 0 ]]; then
    # Append a block for each enabled profile
    PROFILE_BLOCK="## Job profiles configured:"$'\n'
    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Any profile passing all its criteria drives an application (single-profile-passes rule)."$'\n'
    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Record which profile drove each application in the screening report."$'\n'
    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Target companies (watchlist): $(jq -r '.targetCompanies | join(", ")' <<<"$JOB_CONFIG" 2>/dev/null)"$'\n'
    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Resolved company boards and apply-channel URLs:"$'\n'
    
    # Add company boards (resolved)
    BOARDS="$(jq -r '.companyBoards[]? | "\(.company): \(.careersUrl)"' <<<"$JOB_CONFIG" 2>/dev/null | sed 's/^/  - /')"
    if [[ -n "$BOARDS" ]]; then
      PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"$BOARDS"$'\n'
    fi
    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Cooldown days (stale company filter): $(jq -r '.cooldownDays // "not configured"' <<<"$JOB_CONFIG" 2>/dev/null)"$'\n'

    # Render each profile's full criteria: name, employment country, remote
    # model, salary band, Glassdoor minimum, EOR/entity-verification rules,
    # working language, and accepted/rejected role types. The agent matches
    # each posting against these instead of the RUNBOOK.md §2 defaults, and
    # must quote the matched profile's name back with get_job_profiles /
    # recommend_salary.
    PROFILE_CRITERIA="$(jq -r "$PROFILE_CRITERIA_JQ" <<<"$JOB_CONFIG" 2>/dev/null)"
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
      log "unrecognized auth type from app; using container ANTHROPIC_API_KEY"
    fi
    unset CREDS AUTH_TOKEN
  else
    log "credential fetch failed; falling back to container ANTHROPIC_API_KEY"
  fi
fi
MODEL_ARGS=()
[[ -n "$AGENT_MODEL" ]] && MODEL_ARGS=(--model "$AGENT_MODEL")

log "invoking claude..."

# Playwright's mcp__plugin_playwright_playwright__* tools from the Jobs
# original are dropped: agent/mcp.json documents Playwright as a fallback
# only and does not configure it as a live server, because agent/Dockerfile
# deliberately installs no browser (see its BROWSER STRATEGY comment) - a
# Playwright entry here could not launch anything.
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
    "mcp__interceptor__interceptor_browser" \
    "mcp__interceptor__interceptor_read" \
    "mcp__interceptor__interceptor_local" \
  </dev/null >>"$RUN_LOG" 2>&1

RC=$?
log "claude exited rc=$RC"

log "=== run complete: $RUN_LOG ==="
exit $RC
