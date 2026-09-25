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

# per-channel (default): the run is driven as up to three sequential harness
# sessions sharing this TRUTHCV_RUN_ID — (1) approved queue + feed, (2)
# direct-search boards, (3) dork queries — each closing with finish_phase
# except the last, which closes with finish_run. single: today's one-session
# run, byte-for-byte including the composed prompt.
AGENT_SESSION_MODE="${AGENT_SESSION_MODE:-per-channel}"
case "$AGENT_SESSION_MODE" in
  single|per-channel) ;;
  *) echo "invalid AGENT_SESSION_MODE '$AGENT_SESSION_MODE' (expected single|per-channel)" >&2; exit 1 ;;
esac

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

# agent/prompt.md carries the operating instructions (it references
# agent/RUNBOOK.md and names the eleven tools); this script adds the date and,
# below, inlines the RUNBOOK text the prompt refers to.
PROMPT="$(cat "$PROMPT_FILE")"$'\n\n'"Today is $(date +%Y-%m-%d)."

# agent/prompt.md tells the agent to "read agent/RUNBOOK.md in full before
# doing anything else". The harness's only file-reading tool is
# read_runbook_section (agent/harness/builtins/readRunbook.ts) — it returns
# one named section of RUNBOOK.md on request and takes no path argument, so
# it cannot read anything else. The full 39.8KB RUNBOOK no longer travels in
# this permanently-pinned first message (every token here is paid on every
# turn of the run, cached or not, for the life of the conversation): only its
# non-negotiable rules/invariants are inlined below, verbatim from the file,
# plus a table of contents of every section heading. Every other section —
# the per-phase how-to — is fetched on demand with read_runbook_section, and
# the agent is told to do so before starting the phase it covers.
# $RUNBOOK is checked readable in the preconditions above.
#
# The ranges below are section numbers, not headings, so a RUNBOOK edit that
# only changes prose (not renumbers a section) needs no change here; a
# renumbering does, and test-prompt-render.sh's Case 12 plus this script
# failing to find a "## N." marker (awk silently prints nothing for a range
# whose start never matches) are the signals that it drifted.
RUNBOOK_TOC="$(grep -E '^##[^#]' "$RUNBOOK" | sed -E 's/^##[[:space:]]*/- /')"
RUNBOOK_RULES="$(awk '
  /^## 1\. There is no daily quota/,/^## 2\./   { if ($0 !~ /^## 2\./) print }
  /^## 4\. Truthfulness rules/,/^## 5\./         { if ($0 !~ /^## 5\./) print }
  /^## 7\. When something is ambiguous/,/^## 8\./ { if ($0 !~ /^## 8\./) print }
  /^## 8\. Never do/,/^## 9\./                    { if ($0 !~ /^## 9\./) print }
' "$RUNBOOK")"

PROMPT="$PROMPT"$'\n\n'"## Operating spec (agent/RUNBOOK.md) — non-negotiable rules

Also non-negotiable, detailed in the full section — call read_runbook_section
with EXACTLY this heading text (section numbers included, case-insensitive)
before you need it:
- \"0. The approved queue — work it first\": approved-queue postings are
  applied to before anything new is discovered, every run.
- \"2. Hard filters — every criterion of the matched profile must pass\":
  every criterion of the matched profile must pass, no exceptions, no
  judgment calls.
- \"3. Canonical answers — call \`get_profile_answers\`\": screening-question
  answers come only from get_profile_answers, never invented or guessed.
- \"5. Applying\" (its \"Both documents go up\" subsection): a passing
  posting gets a CV **and** a cover letter — never one without the other to
  save cost.
- record_screening REJECTS the call and stores nothing unless company,
  verdict, role and url all carry usable values, on every screening you
  record, rejections included (see \"6. The approve/deny boundary\")."$'\n\n'"$RUNBOOK_RULES"$'\n\n'"## Operating spec — table of contents

Call read_runbook_section(section: <heading text below, exactly as written,
including its number>) for a section's full procedure before you start the
phase it covers — its detail is not inlined here. A \"##\" section's fetch
also returns its \"###\" subsections (e.g. fetching \"5. Applying\" includes
\"Both documents go up\")."$'\n\n'"$RUNBOOK_TOC"

PROMPT="$PROMPT"$'\n\n'"## Run identity

Your run id for this run is: $TRUTHCV_RUN_ID

Call start_run ONCE, at the very beginning, passing this run id. Keep passing
this same run_id on every subsequent tool call that accepts one (e.g.
get_approved_applications, record_application). Before you exit — including
if you are stopping early — call finish_run with this run_id and an honest
stopped_reason describing where you stopped. A run that ends without calling
finish_run is indistinguishable from one that crashed."

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
the employer's publication date in posted_date when the board states one,
the enabled profile's name you screened against in profile, what the
posting itself says about remote work — remote, hybrid, on_site, or
unstated when it does not say — in remote_arrangement, and any language the
posting EXPLICITLY requires (e.g. 'German') in language_requirement, or ''
when it states none. Also pass the posting's own stated salary in
salary_stated, its own stated employment country in
employment_country_stated, its own stated role type (e.g. 'contract',
'full-time') in role_type_stated, and whether the posting states hiring is
through an EOR / employer-of-record arrangement in eor_stated ('yes' when
the posting states employment IS via an EOR, 'no' when it states direct
employment, 'unstated' when you looked and it does not say, or '' when not
applicable). All four are the posting's OWN stated values, never the
profile's, and none of them is mandatory; '' is a legitimate, common
answer, not an omission.
company, verdict, role and url are each required.
It enters the operator's approval queue; they draft the letter and decide.

record_screening REJECTS the call and stores nothing unless company, verdict,
role and url all carry usable values — this applies to every screening you
record, rejections included, not only to passing ones. A \"passed\" verdict
is also rejected, storing nothing, without usable posting_text — a real
posting body, not a login wall or a 404 page; a posting you could not read
takes a screening_blocker instead. A \"passed\" or \"deferred\" verdict is
also rejected, storing nothing, without usable profile and remote_arrangement
values. Evidence that contradicts any of the profile's six hard
requirements (remote model, working language, salary floor, employment
country, rejected role types, or EOR) is stored as an automatic rejection —
not an error to retry, and never fabricate 'remote'/'' to get past it.

Phase 0 is unchanged: postings the operator already approved ARE applied to,
using the cover_letter text that arrives with each item, verbatim."
else
  PROMPT="$PROMPT"$'\n\n'"## Autonomy mode: FULL AUTO

A posting that passes every criterion is applied to this run, as described in
agent/RUNBOOK.md. On every record_screening call pass the employing entity's
name in company, the verdict (rejected, passed or deferred) in verdict, the
posting's own job title (as posted, not a placeholder) in role, the posting's
own URL in url, the full posting text in posting_text, the employer's
publication date in posted_date when the board states one, the enabled
profile's name you screened against in profile, what the posting itself says
about remote work — remote, hybrid, on_site, or unstated when it does not
say — in remote_arrangement, and any language the posting EXPLICITLY
requires (e.g. 'German') in language_requirement, or '' when it states none.
Also pass the posting's own stated salary in salary_stated, its own stated
employment country in employment_country_stated, its own stated role type
(e.g. 'contract', 'full-time') in role_type_stated, and whether the posting
states hiring is through an EOR / employer-of-record arrangement in
eor_stated ('yes' when the posting states employment IS via an EOR, 'no'
when it states direct employment, 'unstated' when you looked and it does
not say, or '' when not applicable). All four are the posting's OWN stated
values, never the profile's, and none of them is mandatory; '' is a
legitimate, common answer, not an omission.

record_screening REJECTS the call and stores nothing unless company, verdict,
role and url all carry usable values. A \"passed\" or \"deferred\" verdict is
also rejected, storing nothing, without usable posting_text — a real posting
body, not a login wall or a 404 page; a posting you could not read takes a
screening_blocker instead. profile and remote_arrangement are also required
for a passed/deferred verdict. Evidence that contradicts any of the
profile's six hard requirements (remote model, working language, salary
floor, employment country, rejected role types, or EOR) is stored as an
automatic rejection — not an error to retry, and never fabricate
'remote'/'' to get past it."
fi

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
# Discovery-channel sections are accumulated separately from PROFILE_BLOCK
# (the shared header) and PROFILE_TAIL (cooldown/freshness/profile criteria,
# also shared) so a per-channel session can compose header+its own
# channel+tail, while single-session mode concatenates all three channels
# between header and tail exactly as before. Pre-declared (set -u) so a
# JOB_CONFIG fetch failure below still leaves every one of them defined-empty.
PROFILE_BLOCK=""
PROFILE_TAIL=""
FEED_SECTION=""
DIRECT_SECTION=""
DORK_SECTION=""
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

    # Discovery channels are rendered in the order the RUNBOOK requires them
    # worked: feed, then direct boards, then dork queries.

    # Postings pulled from API-backed job boards by the app. Unlike the
    # composed queries below these are already-matched postings, not entry
    # points to search from — each line is a URL the agent can open and
    # fetch full posting text (metadata/URL alone is not the posting) and
    # screen-and-record each feed result before direct boards, dorks or new
    # applications. Phase 0 approved work still comes first; normal criteria,
    # freshness, cooldown, autonomy and budgets still bind.
    #
    # Two distinct groups share this response and must NOT share one claim:
    # Remote Rocketship postings (jobfeeds.remoterocketship) are matched
    # against a specific enabled profile and carry that profile's name in
    # `.profile`, so the "pre-filtered" claim below is broadly true for them —
    # but not absolutely: filters_for_profile sets
    # showJobsWithoutSalaryWithMinSalaryFilter, so a posting stating no salary
    # still comes back even with a salary floor set, and per the board's own
    # docs a location outside its known set narrows nothing. The header is
    # worded to not overclaim either. Postings pulled straight from a
    # watchlist company's own ATS (jobfeeds.ats) carry NO profile — that
    # fetcher applies only a freshness window, no keyword/location/salary
    # filtering — so even the hedged claim would be false for them. The two
    # groups are told apart below by whether `.profile` is set, since only
    # Remote Rocketship ever sets it; an empty `.profile` renders as "Company
    # board" rather than an empty "[]".
    #
    # Field names are the API's camelCase wire shape (api/schemas.py emits by
    # alias), not jobfeeds' snake_case dataclass fields — agent-config.js
    # passes the response through untouched. The source/tier bracket is built
    # from whichever of the two is present, joined with "/" only when both
    # are, so tier still renders on a posting with no source (e.g. an older
    # app image serving no source).
    FEED_PROFILE_MATCHED="$(jq -r '.feedPostings[]? | select((.profile // "") != "") | "  - [\(.profile)] \(.title)\(if (.company // "") != "" then " — " + .company else "" end)\(if (.salaryRange // "") != "" then " (" + .salaryRange + ")" else "" end)\(if ((.source // "") != "" or (.tier // "") != "") then " [" + ([(.source // ""), (.tier // "")] | map(select(. != "")) | join("/")) + "]" else "" end)\n    \(.url)"' <<<"$JOB_CONFIG")"
    if [[ -n "$FEED_PROFILE_MATCHED" ]]; then
      FEED_SECTION="$FEED_SECTION"$'\n'"Postings pulled from your API-backed job boards (metadata and URLs, not guaranteed full text; pre-filtered by the board's own keyword and location matching, where the board supports it; a posting naming no salary can still appear even with a salary floor set — open each URL for full text and screen-and-record before direct-board/dork discovery or new applications; postings are still subject to every profile criterion):"$'\n'
      FEED_SECTION="$FEED_SECTION"$'\n'"$FEED_PROFILE_MATCHED"$'\n'
    fi

    FEED_COMPANY_BOARDS="$(jq -r '.feedPostings[]? | select((.profile // "") == "") | "  - [Company board] \(.title)\(if (.company // "") != "" then " — " + .company else "" end)\(if (.salaryRange // "") != "" then " (" + .salaryRange + ")" else "" end)\(if ((.source // "") != "" or (.tier // "") != "") then " [" + ([(.source // ""), (.tier // "")] | map(select(. != "")) | join("/")) + "]" else "" end)\n    \(.url)"' <<<"$JOB_CONFIG")"
    if [[ -n "$FEED_COMPANY_BOARDS" ]]; then
      FEED_SECTION="$FEED_SECTION"$'\n'"Postings pulled directly from watchlist companies' own applicant-tracking systems — NOT filtered by profile keywords, locations or salary floor (only a freshness window); screen each fully against your profile criteria before applying:"$'\n'
      FEED_SECTION="$FEED_SECTION"$'\n'"$FEED_COMPANY_BOARDS"$'\n'
    fi

    FEED_ALREADY_SCREENED="$(jq -r '.feedAlreadyScreened // 0' <<<"$JOB_CONFIG")"
    if [[ "$FEED_ALREADY_SCREENED" -gt 0 ]]; then
      FEED_SECTION="$FEED_SECTION"$'\n'"${FEED_ALREADY_SCREENED} feed posting(s) already screened in earlier runs were omitted from the list above; do not look for them. The feed is only the first of three channels: after it, always work every direct-search board and composed query below."$'\n'
    fi

    # A feed failure is rendered rather than swallowed: an empty feed and a
    # rejected API key look identical in the prompt otherwise, and the agent
    # would silently apply to fewer jobs with nothing in the run log saying why.
    FEED_ERROR="$(jq -r '.feedError // ""' <<<"$JOB_CONFIG")"
    if [[ -n "$FEED_ERROR" ]]; then
      FEED_SECTION="$FEED_SECTION"$'\n'"Job board feed warning: ${FEED_ERROR} Continue the run using the other discovery channels; do not treat this as a reason to stop."$'\n'
    fi

    # Direct-search boards: searched on the board's own site rather than via
    # a Google dork (e.g. it has no useful `site:` search surface). Per-profile
    # search criteria (keywords/locations/avoid) are printed ONCE, in a
    # preamble, rather than once per board — several direct boards commonly
    # share the same enabled profiles, and repeating the criteria per board
    # only bloats the prompt without adding information. The board lines below
    # then carry only the URL and sign-in URL. On hitting a login wall, report
    # the board with report_apply_failure(blocker="login_required", signin_url)
    # and move on to the next board — see RUNBOOK.md.
    DIRECT_CRITERIA="$(jq -r '[.directBoards[]? | .profiles[]?] | unique_by(.profile)[] | "  [\(.profile)] keywords: \(.keywords // [] | join(", "))" + (if ((.locations // []) | length) > 0 then "; locations: \(.locations | join(", "))" else "" end) + (if ((.rejectedRoleTypes // []) | length) > 0 then "; avoid: \(.rejectedRoleTypes | join(", "))" else "" end)' <<<"$JOB_CONFIG")"
    DIRECT_BOARDS="$(jq -r '.directBoards[]? | "  - \(.url)" + (if (.signinUrl // "") != "" then " (sign in: \(.signinUrl))" else "" end)' <<<"$JOB_CONFIG")"
    if [[ -n "$DIRECT_BOARDS" ]]; then
      DIRECT_SECTION="$DIRECT_SECTION"$'\n'"Direct-search boards (search each on the board's own site using the per-profile criteria listed once below; on a login wall, report_apply_failure with blocker \"login_required\" and the sign-in URL, then continue to the next board):"$'\n'
      if [[ -n "$DIRECT_CRITERIA" ]]; then
        DIRECT_SECTION="$DIRECT_SECTION"$'\n'"$DIRECT_CRITERIA"$'\n'
      fi
      DIRECT_SECTION="$DIRECT_SECTION"$'\n'"$DIRECT_BOARDS"$'\n'
    fi

    # Add composed search queries (deterministic entry points, not a boundary
    # on discovery): built from each enabled profile's keywords and locations,
    # and the configured job boards. The agent may open them with WebSearch or
    # the browser as it prefers; free-form WebSearch remains available
    # alongside them.
    QUERIES="$(jq -r '.searchQueries[]? | "  - [\(.profile)] \(.source): \(.query)\n    \(.url)"' <<<"$JOB_CONFIG")"
    if [[ -n "$QUERIES" ]]; then
      DORK_SECTION="$DORK_SECTION"$'\n'"Composed search queries (deterministic entry points from keywords/locations and the configured job boards; use WebSearch or the browser, free-form search still applies too):"$'\n'
      DORK_SECTION="$DORK_SECTION"$'\n'"$QUERIES"$'\n'
    fi

    PROFILE_TAIL="$PROFILE_TAIL"$'\n'"Cooldown days (stale company filter): $(jq -r '.cooldownDays // "not configured"' <<<"$JOB_CONFIG")"$'\n'

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
    PROFILE_TAIL="$PROFILE_TAIL"$'\n'"$AGE_LINE"$'\n'

    # Render each profile's full criteria: name, employment country, remote
    # model, salary band, Glassdoor minimum, EOR/entity-verification rules,
    # working language, and accepted/rejected role types. The agent matches
    # each posting against these instead of the RUNBOOK.md §2 defaults, and
    # must quote the matched profile's name back with get_job_profiles /
    # recommend_salary.
    PROFILE_CRITERIA="$(jq -r "$PROFILE_CRITERIA_JQ" <<<"$JOB_CONFIG")"
    if [[ -n "$PROFILE_CRITERIA" ]]; then
      PROFILE_TAIL="$PROFILE_TAIL"$'\n'"Profile criteria (call get_job_profiles to re-fetch verbatim; call"$'\n'"recommend_salary with the matched profile's name for any salary-expectation field):"$'\n\n'"$PROFILE_CRITERIA"$'\n'
    fi

    # Single-session mode folds every channel into PROMPT right here, in
    # RUNBOOK order, exactly as before per-channel sessions existed. In
    # per-channel mode PROMPT stays the shared core (no channel content) and
    # each session composes header+its own channel+tail for itself, below.
    if [[ "$AGENT_SESSION_MODE" == "single" ]]; then
      PROMPT="$PROMPT"$'\n\n'"$PROFILE_BLOCK$FEED_SECTION$DIRECT_SECTION$DORK_SECTION$PROFILE_TAIL"
    fi
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
if [[ "$AGENT_SESSION_MODE" == "single" && "$APPLY_CAP" =~ ^[1-9][0-9]*$ ]]; then
  PROMPT="$PROMPT"$'\n\n'"Apply to at most $APPLY_CAP role(s) this run."
fi

# Fetch routed LLM credentials from the app (Stage 2) and export them as the
# provider-neutral variables the harness consumes (AGENT_LLM_*). Fallback (when
# AGENT_API_TOKEN is unset): the container's own AGENT_LLM_* environment — the
# docker-compose-level provider-neutral vars — exactly the pre-Stage-2 spirit,
# just no longer Anthropic-only.
AGENT_MODEL=""
if [[ -n "${AGENT_API_TOKEN:-}" ]]; then
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
else
  # No app-issued agent token: take the provider-neutral credentials straight
  # from the container's own environment (the docker-compose-level AGENT_LLM_*
  # vars) instead of the app.
  export AGENT_LLM_PROVIDER="${AGENT_LLM_PROVIDER:-}"
  export AGENT_LLM_MODEL="${AGENT_LLM_MODEL:-}"
  export AGENT_LLM_API_KEY="${AGENT_LLM_API_KEY:-}"
  export AGENT_LLM_BASE_URL="${AGENT_LLM_BASE_URL:-}"
  export AGENT_LLM_WIRE="${AGENT_LLM_WIRE:-}"
  export AGENT_LLM_AUTH_TYPE="${AGENT_LLM_AUTH_TYPE:-}"
  AGENT_MODEL="$AGENT_LLM_MODEL"
fi

# Final gate: the harness needs a known provider AND a usable credential for it.
# claude|codex|openrouter each require a non-empty token; ollama legitimately
# has none and requires a base URL instead.
case "$AGENT_LLM_PROVIDER" in
  claude|codex|openrouter)
    [[ -n "$AGENT_LLM_API_KEY" ]] || abort "no usable LLM credential for provider '$AGENT_LLM_PROVIDER': set AGENT_API_TOKEN + app credentials, or AGENT_LLM_API_KEY in the container env"
    ;;
  ollama)
    [[ -n "$AGENT_LLM_BASE_URL" ]] || abort "provider 'ollama' requires a base URL: set AGENT_LLM_BASE_URL"
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
# run_harness takes the prompt file and finish-tool name as arguments so a
# per-channel run can invoke it once per session, each with its own prompt
# and its own --finish-tool (finish_phase for every non-final session,
# finish_run for the last).
run_harness() {
local prompt_file="$1" finish_tool="$2"
node "$HARNESS_CLI" \
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
  --screening-model "${AGENT_SCREENING_MODEL:-$AGENT_MODEL}" \
  --screening-provider "${AGENT_SCREENING_PROVIDER:-$AGENT_LLM_PROVIDER}" \
  --screening-wire "${AGENT_SCREENING_WIRE:-$AGENT_LLM_WIRE}" \
  --screening-token "${AGENT_SCREENING_API_KEY:-$AGENT_LLM_API_KEY}" \
  --screening-base-url "${AGENT_SCREENING_BASE_URL:-$AGENT_LLM_BASE_URL}" \
  --screening-auth-type "${AGENT_SCREENING_AUTH_TYPE:-$AGENT_LLM_AUTH_TYPE}" \
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
# (run not yet recorded, network error, malformed body) so a per-channel
# session never blocks on this becoming available.
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
      const n = Number(rec.applications_submitted);
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

# The '## This session' block: names the channel this session works, states
# the others run in separate sessions sharing this run_id and must not be
# worked here, and names the finish tool that ends this session.
render_session_block() {
  local channel="$1" finish_tool="$2" desc
  case "$channel" in
    feed) desc="the approved-application queue and the job-board feed" ;;
    direct) desc="the direct-search boards" ;;
    dork) desc="the composed dork queries" ;;
  esac
  printf '\n\n## This session\n\nThis session works ONLY %s (channel: "%s"). The other discovery channels run\nin separate sessions that share this run_id; do not work them here.\n\nWhen this channel is fully worked, call %s(run_id, channel: "%s", note: ...%s) to end this session.' \
    "$desc" "$channel" "$finish_tool" "$channel" \
    "$([[ "$finish_tool" == finish_run ]] && printf '' || printf '')"
}

# Runs one harness session, logging its channel and rc; fd 3 (when present)
# stays open across every session in the run and is closed once, after the
# last session, by the caller.
run_session() {
  local prompt_file="$1" finish_tool="$2" channel="$3"
  log "session start: channel=$channel finish-tool=$finish_tool"
  run_harness "$prompt_file" "$finish_tool"
  local rc=$?
  log "session end: channel=$channel rc=$rc"
  return $rc
}

FD3_OPEN=0
if [[ "${TRUTHCV_DIAGNOSTICS_FD:-}" == 3 && -e /dev/fd/3 ]]; then
  FD3_OPEN=1
else
  unset TRUTHCV_DIAGNOSTICS_FD
fi

FINAL_RC=0
FINAL_RC_SET=0

if [[ "$AGENT_SESSION_MODE" == "single" ]]; then
  HARNESS_PROMPT_FILE="$(mktemp)"
  printf '%s' "$PROMPT" >"$HARNESS_PROMPT_FILE"
  run_session "$HARNESS_PROMPT_FILE" finish_run single
  FINAL_RC=$?
  rm -f "$HARNESS_PROMPT_FILE"
else
  # Sessions in RUNBOOK order; a channel with no configured data is omitted.
  # 'feed' (approved queue + job-board feed) always runs: Phase 0 (the
  # approved queue) is unconditional. The last present session finishes with
  # finish_run; every session before it finishes with finish_phase.
  SESSION_CHANNELS=(feed)
  [[ -n "$DIRECT_SECTION" ]] && SESSION_CHANNELS+=(direct)
  [[ -n "$DORK_SECTION" ]] && SESSION_CHANNELS+=(dork)
  LAST_INDEX=$(( ${#SESSION_CHANNELS[@]} - 1 ))

  for i in "${!SESSION_CHANNELS[@]}"; do
    CHANNEL="${SESSION_CHANNELS[$i]}"
    case "$CHANNEL" in
      feed) CHANNEL_SECTION="$FEED_SECTION" ;;
      direct) CHANNEL_SECTION="$DIRECT_SECTION" ;;
      dork) CHANNEL_SECTION="$DORK_SECTION" ;;
    esac
    if (( i == LAST_INDEX )); then
      SESSION_FINISH_TOOL="finish_run"
    else
      SESSION_FINISH_TOOL="finish_phase"
    fi

    SESSION_PROMPT="$PROMPT"
    if [[ -n "$PROFILE_BLOCK" ]]; then
      SESSION_PROMPT="$SESSION_PROMPT"$'\n\n'"$PROFILE_BLOCK$CHANNEL_SECTION$PROFILE_TAIL"
    fi
    REMAINING_LINE="$(render_remaining_line "$APPLY_CAP")"
    if [[ -n "$REMAINING_LINE" ]]; then
      SESSION_PROMPT="$SESSION_PROMPT"$'\n\n'"$REMAINING_LINE"
    fi
    SESSION_PROMPT="$SESSION_PROMPT$(render_session_block "$CHANNEL" "$SESSION_FINISH_TOOL")"

    SESSION_PROMPT_FILE="$(mktemp)"
    printf '%s' "$SESSION_PROMPT" >"$SESSION_PROMPT_FILE"
    run_session "$SESSION_PROMPT_FILE" "$SESSION_FINISH_TOOL" "$CHANNEL"
    SESSION_RC=$?
    rm -f "$SESSION_PROMPT_FILE"

    if (( FINAL_RC_SET == 0 )); then
      FINAL_RC=$SESSION_RC
      FINAL_RC_SET=1
    fi

    if [[ "$SESSION_RC" == 3 || "$SESSION_RC" == 4 || "$SESSION_RC" == 5 ]]; then
      # Provider/MCP/config failures abort the rest of the run immediately;
      # later sessions cannot succeed either.
      break
    fi
    # rc 0 or (2 turn-cap / 6 no-finish) both fall through to the next
    # session; 2/6 are logged above and recorded as FINAL_RC only if no
    # earlier session already set a non-zero FINAL_RC.
    if (( FINAL_RC == 0 && SESSION_RC != 0 )); then
      FINAL_RC=$SESSION_RC
    fi
  done
fi

if (( FD3_OPEN )); then
  exec 3>&-
fi

RC=$FINAL_RC
log "agent harness exited rc=$RC"

log "=== run complete: $RUN_LOG ==="
exit $RC
