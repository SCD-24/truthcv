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
# Which of agent/mcp.json's two browser drivers this run may use. Defaults to
# the self-contained containerised browser; `interceptor` switches to the
# operator's HOST Chrome and requires docker-compose.interceptor.yml. Every
# driver-specific block below keys off this one variable.
AGENT_BROWSER_DRIVER="${AGENT_BROWSER_DRIVER:-browser}"

# The containerised Chromium's MCP endpoint (docker-compose.yml `browser`
# service, browser/Dockerfile). Same default as agent/mcp.json's
# ${BROWSER_MCP_URL:-...} expansion, so the probe below and the server the
# claude CLI actually dials cannot drift apart.
BROWSER_MCP_URL="${BROWSER_MCP_URL:-http://browser:8931/mcp}"

# Interceptor driver settings. Same defaults as agent/mcp.json's `interceptor`
# entry, for the same anti-drift reason. Inert unless that driver is selected.
INTERCEPTOR_SOCKET="${INTERCEPTOR_SOCKET:-/tmp/interceptor.sock}"
INTERCEPTOR_BIN="${INTERCEPTOR_BIN:-/opt/interceptor/bin/interceptor}"
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
    ;;

  interceptor)
    # The Interceptor binary is bind-mounted read-only into the container at
    # /opt/interceptor/bin/interceptor by docker-compose.interceptor.yml, and
    # spawned by the claude CLI as an MCP server over stdio. The binary shells
    # to the real `interceptor <verb>` command to reach the host daemon. Without
    # the mount the MCP server cannot start, and because a missing bind-mount
    # source makes Docker create a DIRECTORY at the target, the failure would
    # otherwise surface as something far less obvious than "not executable".
    [[ -x "$INTERCEPTOR_BIN" ]] || abort "interceptor binary not executable: $INTERCEPTOR_BIN - is docker-compose.interceptor.yml in the -f list, and is INTERCEPTOR_BIN_HOST correct? (\`command -v interceptor\` on the host)"

    # The Jobs original also required a live Chrome process (`pgrep -x chrome` /
    # `pgrep -f google-chrome`) so interceptor had a browser on the same machine
    # to attach to. That check cannot survive containerisation: this agent runs
    # in its own container while Chrome runs on the HOST, so the container's
    # process table will never show it - kept unchanged it would abort every
    # single run, unconditionally, which is as useless as deleting it outright.
    # The honest replacement is to check that the socket is actually live
    # (accepting connections), not merely a stale file left behind by an
    # interceptor process that has since died. This image has no tool that can
    # dial a unix socket to test that - agent/Dockerfile installs only
    # ca-certificates, tzdata, jq and the claude CLI, no nc/socat/curl - so that
    # connectability probe cannot be done with those. The base image does ship
    # node, which CAN dial a unix socket - agent/smoke-test.sh uses it for
    # exactly this - but a probe here would open and drop a connection on the
    # operator's live browser daemon before every run, so it is kept in the
    # smoke test where it is run deliberately. The -S check below is therefore
    # the only guard on the run path; a present-but-dead socket surfaces when
    # the interceptor MCP server fails to respond mid-run.
    [[ -S "$INTERCEPTOR_SOCKET" ]] || abort "interceptor socket absent: $INTERCEPTOR_SOCKET - is the interceptor daemon running on the host?"
    ;;

  *)
    # Fail closed rather than silently granting no browser tools at all: an
    # unattended run that cannot apply to anything should say why, not spend an
    # LLM budget searching and then quietly skip every posting it finds.
    abort "unknown AGENT_BROWSER_DRIVER '$AGENT_BROWSER_DRIVER' - expected 'browser' or 'interceptor'"
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
  log "agent mode is off - skipping run"
  exit 0
elif [[ "$AGENT_MODE" != "semi" && "$AGENT_MODE" != "full" ]]; then
  abort "agent config unreachable or mode unrecognised ('$AGENT_MODE') - skipping run (fail closed)"
fi
log "agent mode: $AGENT_MODE"

# --- Run ---------------------------------------------------------------------

# agent/prompt.md carries the operating instructions (it references
# agent/RUNBOOK.md and names the eleven tools); this script only adds the date.
PROMPT="$(cat "$PROMPT_FILE")"$'\n\n'"Today is $(date +%Y-%m-%d)."

# The mode changes what the agent does with a posting that passes every
# criterion, so it is rendered into the prompt rather than left implicit. The
# queueing itself is enforced server-side in screening.store.create - this text
# tells the agent what to expect, it is not what makes it true.
if [[ "$AGENT_MODE" == "semi" ]]; then
  PROMPT="$PROMPT"$'\n\n'"## Autonomy mode: SEMI-AUTO

Do NOT apply to a posting you find this run, however well it scores, and do not
write a cover letter for it. For a posting that passes every criterion, call
record_screening passing \"passed\" in verdict, the employing entity's name
in company, the posting's own job title (as posted, not a placeholder)
in role, the posting's own URL in url, the full posting text in posting_text,
and the employer's publication date in posted_date when the board states one.
company, verdict, role and url are each required.
It enters the operator's approval queue; they draft the letter and decide.

record_screening REJECTS the call and stores nothing unless company, verdict,
role and url all carry usable values — this applies to every screening you
record, rejections included, not only to passing ones.

Phase 0 is unchanged: postings the operator already approved ARE applied to,
using the cover_letter text that arrives with each item, verbatim."
else
  PROMPT="$PROMPT"$'\n\n'"## Autonomy mode: FULL AUTO

A posting that passes every criterion is applied to this run, as described in
agent/RUNBOOK.md. On every record_screening call pass the employing entity's
name in company, the verdict (rejected, passed or deferred) in verdict, the
posting's own job title (as posted, not a placeholder) in role, the posting's
own URL in url, the full posting text in posting_text, and the employer's
publication date in posted_date when the board states one.

record_screening REJECTS the call and stores nothing unless company, verdict,
role and url all carry usable values."
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
# currency is exposed on the wire (api/schemas.py JobProfileModel) and may be
# null: no regional default exists, so a band without a configured currency
# renders as "not configured" rather than quoting a currency the user never
# chose.
PROFILE_CRITERIA_JQ='
def fmt_bool: if . == null then "not configured" elif . then "true" else "false" end;
def fmt_list: if (. // []) | length > 0 then (. // [] | join(", ")) else "not configured" end;
def fmt_band(min_v; max_v; cur): if (min_v != null and max_v != null and cur != null) then "\(min_v) - \(max_v) \(cur)" else "not configured" end;
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

# Job profiles: the run's search criteria. The agent has no built-in policy:
# without at least one enabled profile there is nothing to search for, so the
# run aborts before invoking the LLM instead of silently applying someone
# else's defaults.
if JOB_CONFIG="$(node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" job_config 2>/dev/null)"; then
  # A malformed payload must not read as "zero profiles configured": that
  # message sends the operator to add profiles they already have. Probe the
  # payload's shape first, so a broken config gets its own diagnosis. The
  # every() guard catches non-object elements, which jq would otherwise skip
  # silently (or error on, depending on version).
  if ! jq -e '.profiles // [] | (type == "array") and all(.[]; type == "object" or . == null)' <<<"$JOB_CONFIG" >/dev/null; then
    abort "Agent config fetched but is malformed (.profiles is missing, not an array, or contains non-object entries) - fix data/agent_config.json or the Agents page before the agent can run"
  fi
  ENABLED_PROFILES="$(jq -r '[.profiles // [] | .[] | select((type == "object") and (.enabled == true))] | length' <<<"$JOB_CONFIG")"
  if [[ "$ENABLED_PROFILES" -eq 0 ]]; then
    abort "No enabled job profiles configured — set your search criteria on the Agents page before the agent can run (config fetch succeeded; it contained zero enabled profiles)"
  fi
  # No stderr suppression on the jq calls in this block: jq is a checked
  # precondition above, so a jq failure here means malformed config, and it
  # must be visible in the run log rather than quietly miscounting profiles.
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

    # Add composed search queries (deterministic entry points, not a boundary
    # on discovery): built from each enabled profile's keywords, locations
    # and preferred sources. The agent may open them with WebSearch or the
    # browser as it prefers; free-form WebSearch remains available alongside
    # them.
    QUERIES="$(jq -r '.searchQueries[]? | "  - [\(.profile)] \(.source): \(.query)\n    \(.url)"' <<<"$JOB_CONFIG")"
    if [[ -n "$QUERIES" ]]; then
      PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Composed search queries (deterministic entry points from keywords/locations/preferred sources; use WebSearch or the browser, free-form search still applies too):"$'\n'
      PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"$QUERIES"$'\n'
    fi

    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"Cooldown days (stale company filter): $(jq -r '.cooldownDays // "not configured"' <<<"$JOB_CONFIG")"$'\n'

    # Discovery freshness window. Rendered as a hard filter rather than only
    # baked into the composed search URLs: WebSearch results and an employer's
    # own board both ignore Google's tbs parameter, so without this the agent
    # would still surface and screen months-old postings from those channels.
    # Only a whole number of days 1..365 is a filter. Anything else — absent,
    # null, 0, a bool, a negative, a hand-edited string — means no age
    # filtering, and must say so rather than falling through to the filter
    # branch. The else-branch used to be the catch-all, so a config holding
    # `true` rendered "true days. HARD FILTER" and `-1` rendered "-1 days.
    # HARD FILTER", while the search side treated both as disabled. Guarded
    # the same way maxApplicationsPerRun is below.
    MAX_AGE="$(jq -r 'if (.maxPostingAgeDays|type) == "number" then (.maxPostingAgeDays|tostring) else "unset" end' <<<"$JOB_CONFIG" 2>/dev/null || echo unset)"
    if [[ "$MAX_AGE" =~ ^[1-9][0-9]*$ ]] && (( MAX_AGE <= 365 )); then
      AGE_LINE="Posting freshness window: ${MAX_AGE} days. HARD FILTER — reject any posting whose stated publication date is older than this, with failing_criterion 'posting_age'. When a board states no date, do NOT infer one and do NOT reject on age."
    else
      # Unset is NOT a rejection rule. Discovery still carries a past-week
      # preference in the composed search URLs, but a posting arriving by any
      # other route is judged on the profile criteria alone — exactly what
      # happened before this setting existed.
      AGE_LINE="Posting freshness window: not configured — a posting's age is never a rejection reason on this run. Prefer recent postings when choosing what to open, but never reject one for being old."
    fi
    PROFILE_BLOCK="$PROFILE_BLOCK"$'\n'"$AGE_LINE"$'\n'

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
# that reason). Only append a limit line when the resolved value is actually
# a positive integer, so the common no-cap case adds nothing to the prompt.
if [[ "$APPLY_CAP" =~ ^[1-9][0-9]*$ ]]; then
  PROMPT="$PROMPT"$'\n\n'"Apply to at most $APPLY_CAP role(s) this run."
fi

# Fetch routed LLM credentials from the app (Stage 2). Fallback: the
# container's ANTHROPIC_API_KEY env, exactly the pre-Stage-2 behavior.
AGENT_MODEL=""
if [[ -n "${AGENT_API_TOKEN:-}" ]]; then
  if CREDS="$(node "${AGENT_CONFIG_JS:-/app/agent/agent-config.js}" llm_credentials 2>/dev/null)"; then
    AUTH_TYPE="$(sed -n 1p <<<"$CREDS")"
    AUTH_TOKEN="$(sed -n 2p <<<"$CREDS")"
    AGENT_MODEL="$(sed -n 3p <<<"$CREDS")"
    AGENT_BASE_URL="$(sed -n 4p <<<"$CREDS")"
    # A base URL means the route points at an Anthropic-compatible third party
    # (OpenRouter) rather than Anthropic itself. The claude CLI appends
    # /v1/messages to ANTHROPIC_BASE_URL and authenticates with
    # ANTHROPIC_AUTH_TOKEN, so ANTHROPIC_API_KEY must be unset or it wins and
    # the run goes to Anthropic with a key that is not one.
    if [[ -n "$AGENT_BASE_URL" ]]; then
      export ANTHROPIC_BASE_URL="$AGENT_BASE_URL"
      export ANTHROPIC_AUTH_TOKEN="$AUTH_TOKEN"
      unset ANTHROPIC_API_KEY
      # The CLI only knows Anthropic's own model ids and warns on anything
      # else while still honouring it; this silences a warning, it does not
      # change which model runs.
      export CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT=1
      log "using $AGENT_BASE_URL credentials from app"
    elif [[ "$AUTH_TYPE" == "oauth" ]]; then
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
[[ -n "${ANTHROPIC_API_KEY:-}" ]] || [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]] || [[ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]] || abort "no usable LLM credential: set ANTHROPIC_API_KEY or AGENT_API_TOKEN + app credentials"
MODEL_ARGS=()
[[ -n "$AGENT_MODEL" ]] && MODEL_ARGS=(--model "$AGENT_MODEL")

# Interceptor MCP settings are exported so the stdio server the claude CLI
# spawns inherits them. Harmless under the `browser` driver, where no such
# server is ever started, but exporting them unconditionally keeps the values in
# one place rather than duplicated per branch.
export INTERCEPTOR_MCP_ALLOW="${INTERCEPTOR_MCP_ALLOW:-}"
export INTERCEPTOR_MCP_FENCE="${INTERCEPTOR_MCP_FENCE:-on}"
export INTERCEPTOR_MCP_GROUP="${INTERCEPTOR_MCP_GROUP:-truthcv-agent}"

# Only the SELECTED driver's tools are granted. agent/mcp.json declares both
# servers, but a declared server the agent holds no grant for is never called,
# so this list - not the MCP config - is what decides which browser is in play.
# Granting both at once is exactly what this avoids: two ways to drive a
# browser, with no rule saying which, is how an unattended run ends up applying
# from the wrong session.
if [[ "$AGENT_BROWSER_DRIVER" == "interceptor" ]]; then
  # The Interceptor tools (interceptor_browser, interceptor_read,
  # interceptor_local) are named per the Interceptor tool table
  # (https://interceptor.ai/docs/concepts/tools-table). Each takes a `verb` plus
  # an `args` string array passed verbatim to the CLI. They ARE enumerated,
  # unlike mcp__browser below, because this router surface is small and fixed:
  # three tools, with the variability living in the verb rather than in the tool
  # names, so a version bump cannot silently rename one out from under us.
  BROWSER_TOOLS=(
    "mcp__interceptor__interceptor_browser"
    "mcp__interceptor__interceptor_read"
    "mcp__interceptor__interceptor_local"
  )
else
  # The containerised browser is granted as the whole server, `mcp__browser`,
  # rather than as an enumerated tool list. Every truthcv grant below is a single
  # named tool, and the asymmetry is deliberate: the truthcv tools are OUR eleven,
  # fixed by agenttools/mcp_app.py (the JSON-RPC surface this agent dials -
  # agenttools/server.py is the separate REST surface and registers only 9) and
  # changing only when we change it, so naming
  # them keeps the blast radius of a new tool at zero until it is granted on
  # purpose. The browser server is upstream @playwright/mcp (browser/Dockerfile),
  # whose tool set - browser_navigate, browser_click, browser_type,
  # browser_file_upload, browser_snapshot, browser_take_screenshot and the rest -
  # is theirs to rename or extend on any version bump; pinning a list here would
  # silently disable whichever tool got renamed, mid-run, in an unattended job.
  # Containment for the browser comes from the container instead: no host
  # filesystem, no host network, its profile on its own volume, and the app data
  # volume mounted read-only.
  #
  # (Superseding the Jobs original's mcp__plugin_playwright_playwright__* grants,
  # which were dropped when this image had no browser at all.)
  BROWSER_TOOLS=("mcp__browser")
fi

log "invoking claude... (browser driver: $AGENT_BROWSER_DRIVER)"

# --dangerously-skip-permissions: this is an unattended run with stdin at
# /dev/null, so any trust or permission prompt would EOF and kill the run. The
# --allowedTools list below, not an interactive prompt, is the actual boundary on
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
    "mcp__truthcv__get_approved_applications" \
    "mcp__truthcv__report_apply_failure" \
    "${BROWSER_TOOLS[@]}" \
  --dangerously-skip-permissions \
  </dev/null >>"$RUN_LOG" 2>&1

RC=$?
log "claude exited rc=$RC"

log "=== run complete: $RUN_LOG ==="
exit $RC
