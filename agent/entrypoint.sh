#!/usr/bin/env bash
# Container entrypoint for the agent service (agent/Dockerfile,
# docker-compose.yml `agent` service, plan agent-container-and-schedule task
# t-3). Ported from the retiring Jobs project's docker/entrypoint.sh.
#
# Modes:
#   RUN_ONCE=1   run immediately, exit with the run's status (use this to test)
#   default      loop: sleep until the next scheduled slot, run, repeat
#
# Schedule is controlled by RUN_AT (comma-separated HH:MM, 24h, resolved in
# the schedule zone: the app's run_timezone, else RUN_TIMEZONE, else TZ)
# and RUN_DAYS (comma-separated 1=Mon .. 7=Sun). The schedule's source of
# truth is the app's agent config (Agents page); env is the fallback used only
# when that config API is unreachable.

set -uo pipefail

RUN_AT_DEFAULT="${RUN_AT:-09:00,15:00}"
RUN_DAYS_DEFAULT="${RUN_DAYS:-1,2,3,4,5}"
# The wall-clock zone the RUN_AT slots are interpreted in. Source of truth is
# the app's agent config (run_timezone); this env value is only the fallback,
# and it falls back in turn to the container's own TZ, which is how the slots
# were resolved before run_timezone existed.
RUN_TIMEZONE_DEFAULT="${RUN_TIMEZONE:-${TZ:-UTC}}"
DAILY_APPLY="${DAILY_APPLY:-/app/agent/daily-apply.sh}"
AGENT_CONFIG_JS="${AGENT_CONFIG_JS:-/app/agent/agent-config.js}"

# RUN_AT/RUN_DAYS hold the active schedule; refresh_schedule() (below) sets
# them from the config API, falling back to the *_DEFAULT values above when
# that API is unreachable. Seed them with the defaults so the pre-refresh
# preflight and startup log line have sane values.
RUN_AT="$RUN_AT_DEFAULT"
RUN_DAYS="$RUN_DAYS_DEFAULT"
RUN_TIMEZONE="$RUN_TIMEZONE_DEFAULT"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

# Chrome is deliberately not in THIS container: the browser is the sibling
# `browser` compose service (headful Chromium under Xvfb served by
# @playwright/mcp), which this agent drives over in-network HTTP MCP at
# ${BROWSER_MCP_URL} - see agent/Dockerfile's BROWSER STRATEGY note and
# agent/mcp.json. There is no in-container Xvfb/Chrome to start - do not add
# one back.

# --- Preconditions -----------------------------------------------------------
# Per-run preconditions (built harness at $HARNESS_CLI, runbook readable, jq
# present, browser MCP reachable, TRUTHCV_MCP_URL set) live in daily-apply.sh
# and are checked there,
# every run - do not duplicate them here. This preflight only checks what is
# worth failing fast at container START, before the first sleep.
# Credential enforcement lives in daily-apply.sh per run.
validate_run_at() {
  local t
  IFS=',' read -ra _slots <<< "$RUN_AT"
  for t in "${_slots[@]}"; do
    [[ "$t" =~ ^[0-9]{2}:[0-9]{2}$ ]] || {
      log "ABORT: malformed RUN_AT entry '$t' (want comma-separated HH:MM)"
      return 1
    }
  done
  return 0
}

# Reports the container's LLM credential posture at boot. Never fatal - actual
# enforcement happens per run in daily-apply.sh - and never logs key/URL values.
report_credentials() {
  if [[ -n "${AGENT_API_TOKEN:-}" ]]; then
    log "INFO: credentials will be fetched from app at run time"
  elif [[ -n "${AGENT_LLM_API_KEY:-}" ]]; then
    log "INFO: using container-level AGENT_LLM_* credentials (provider=${AGENT_LLM_PROVIDER:-unset})"
  elif [[ "${AGENT_LLM_PROVIDER:-}" == "ollama" && -n "${AGENT_LLM_BASE_URL:-}" ]]; then
    log "INFO: using container-level AGENT_LLM_* credentials (provider=ollama)"
  else
    log "WARN: no LLM credential configured - runs will abort until AGENT_API_TOKEN is set and a provider key is saved on the Agents page, or AGENT_LLM_API_KEY is set in the container env"
  fi
  return 0
}

preflight() {
  local ok=0
  report_credentials
  [[ -x "$DAILY_APPLY" ]] || { log "ABORT: $DAILY_APPLY missing or not executable"; ok=1; }

  # Browser-driver switch, validated at BOOT so an unknown value is reported
  # now rather than at the first scheduled run - which may be hours away, and
  # unattended when it arrives. `browser` is the only supported driver; the
  # switch is validated here (rather than dropped) so it fails fast at boot,
  # not mid-run in daily-apply.sh, if it is ever misconfigured. The `browser`
  # service itself is not probed here: compose already gates startup on its
  # healthcheck via depends_on: service_healthy, and agent/daily-apply.sh
  # probes it per run.
  local driver="${AGENT_BROWSER_DRIVER:-browser}"
  case "$driver" in
    browser)
      : ;;
    *)
      log "ABORT: unknown AGENT_BROWSER_DRIVER '$driver' - expected 'browser'"
      ok=1
      ;;
  esac

  validate_run_at || ok=1
  return $ok
}

# --- The run -----------------------------------------------------------------
# All prompt construction, the MCP config flag and the tool allow-list live
# in daily-apply.sh, along with the run log file - this just marks the run's
# boundaries so `docker logs` shows them and propagates its exit code.
do_run() {
  local stamp rc
  stamp="$(date +%Y-%m-%d_%H%M)"
  log "=== run $stamp starting ==="
  "$DAILY_APPLY"
  rc=$?
  log "=== run $stamp finished rc=$rc ==="
  return $rc
}

# --- Scheduling --------------------------------------------------------------
# RUN_AT is a LIST of times, not a single one: find the smallest positive
# delta to any (day, slot) pair within the next few days that also falls on
# an allowed RUN_DAYS weekday.
# Takes an optional "as of" epoch seconds so --check-schedule can walk the
# schedule forward without waiting for it; defaults to now for the run loop.
seconds_until_next_slot() {
  local now best target dow t offset
  now="${1:-$(date +%s)}"
  best=-1
  local -a slots
  IFS=',' read -ra slots <<< "$RUN_AT"
  for offset in $(seq 0 8); do
    for t in "${slots[@]}"; do
      # Slots are wall-clock times in $RUN_TIMEZONE, so the reference date, the
      # slot resolution and the weekday test all read the clock in that zone;
      # the epoch comparison below stays absolute.
      target=$(TZ="$RUN_TIMEZONE" date -d "$(TZ="$RUN_TIMEZONE" date -d "@$now" +%F) +${offset} days ${t}" +%s 2>/dev/null) || return 1
      dow=$(TZ="$RUN_TIMEZONE" date -d "@$target" +%u)
      if [[ ",$RUN_DAYS," == *",$dow,"* ]] && (( target > now )); then
        if (( best == -1 )) || (( target - now < best )); then
          best=$(( target - now ))
        fi
      fi
    done
  done
  (( best >= 0 )) || return 1
  echo "$best"
  return 0
}

# Schedule source of truth is the app's agent config (Agents page); the RUN_AT/
# RUN_DAYS env values are only the fallback when the config API is unreachable.
refresh_schedule() {
  local at days zone
  at="$(node "$AGENT_CONFIG_JS" run_at 2>/dev/null)" || at=""
  days="$(node "$AGENT_CONFIG_JS" run_days 2>/dev/null)" || days=""
  zone="$(node "$AGENT_CONFIG_JS" run_timezone 2>/dev/null)" || zone=""
  RUN_AT="${at:-$RUN_AT_DEFAULT}"
  RUN_DAYS="${days:-$RUN_DAYS_DEFAULT}"
  RUN_TIMEZONE="${zone:-$RUN_TIMEZONE_DEFAULT}"
  SCHEDULE_SOURCE=config
  [[ -n "$at" ]] || SCHEDULE_SOURCE=env
  validate_run_at || {
    RUN_AT="$RUN_AT_DEFAULT"
    RUN_DAYS="$RUN_DAYS_DEFAULT"
    RUN_TIMEZONE="$RUN_TIMEZONE_DEFAULT"
    SCHEDULE_SOURCE=env
  }
}

# Print the next few slots and exit, so the schedule can be checked without
# waiting a day for it. Advisory only: the running loop is supervisor.js, whose
# schedule.mjs resolves the DST edge cases (non-existent and ambiguous local
# times) explicitly, where `date -d` here just takes the system's answer, so on
# a DST transition day the printed instant can differ by an hour. Deliberately runs BEFORE preflight: it submits
# nothing (it only reads the schedule via refresh_schedule), so it must not
# require credentials.
check_schedule() {
  local cursor secs i
  cursor=$(date +%s)
  refresh_schedule
  validate_run_at || return 1
  echo "RUN_AT=$RUN_AT RUN_DAYS=$RUN_DAYS schedule-zone=$RUN_TIMEZONE TZ=${TZ:-unset} source=$SCHEDULE_SOURCE - next ${CHECK_SLOTS:-6} slots:"
  for (( i = 0; i < ${CHECK_SLOTS:-6}; i++ )); do
    secs=$(seconds_until_next_slot "$cursor") || return 1
    cursor=$(( cursor + secs ))
    TZ="$RUN_TIMEZONE" date -d "@$cursor" '+  %a %Y-%m-%d %H:%M %Z'
  done
  return 0
}

# --- Main --------------------------------------------------------------------
if [[ "${1:-}" == "--check-schedule" ]]; then
  check_schedule
  exit $?
fi

log "agent starting (TZ=${TZ:-unset}, schedule-zone=$RUN_TIMEZONE, RUN_AT=$RUN_AT, RUN_DAYS=$RUN_DAYS)"

preflight || exit 1

if [[ "${RUN_ONCE:-0}" == "1" ]]; then
  log "RUN_ONCE set - running immediately"
  do_run
  exit $?
fi

# Hand scheduling and the control-server HTTP surface over to supervisor.js.
# All environment variables are inherited; supervisor.js mirrors the
# seconds_until_next_slot / refresh_schedule logic from this script.
exec node /app/agent/supervisor.js
