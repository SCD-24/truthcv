#!/usr/bin/env bash
# Container entrypoint for the agent service (agent/Dockerfile,
# docker-compose.yml `agent` service, plan agent-container-and-schedule task
# t-3). Ported from the retiring Jobs project's docker/entrypoint.sh.
#
# Modes:
#   RUN_ONCE=1   run immediately, exit with the run's status (use this to test)
#   default      loop: sleep until the next scheduled slot, run, repeat
#
# Schedule is controlled by RUN_AT (comma-separated HH:MM, 24h, container TZ)
# and RUN_DAYS (comma-separated 1=Mon .. 7=Sun). The schedule's source of
# truth is the app's agent config (Agents page); env is the fallback used only
# when that config API is unreachable.

set -uo pipefail

RUN_AT_DEFAULT="${RUN_AT:-09:00,15:00}"
RUN_DAYS_DEFAULT="${RUN_DAYS:-1,2,3,4,5}"
DAILY_APPLY="${DAILY_APPLY:-/app/agent/daily-apply.sh}"
AGENT_CONFIG_JS="${AGENT_CONFIG_JS:-/app/agent/agent-config.js}"

# RUN_AT/RUN_DAYS hold the active schedule; refresh_schedule() (below) sets
# them from the config API, falling back to the *_DEFAULT values above when
# that API is unreachable. Seed them with the defaults so the pre-refresh
# preflight and startup log line have sane values.
RUN_AT="$RUN_AT_DEFAULT"
RUN_DAYS="$RUN_DAYS_DEFAULT"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

# Chrome is deliberately not containerised here: the agent drives the
# operator's real, already-logged-in browser on the HOST over a bind-mounted unix
# socket (see agent/Dockerfile's BROWSER STRATEGY note and agent/mcp.json).
# There is no in-container Xvfb/Chrome to start - do not add one back.

# --- Preconditions -----------------------------------------------------------
# Per-run preconditions (claude CLI, runbook readable, interceptor socket
# present, TRUTHCV_MCP_URL set) live in daily-apply.sh and are checked there,
# every run - do not duplicate them here. This preflight only checks what is
# worth failing fast at container START, before the first sleep.
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

preflight() {
  local ok=0
  if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${AGENT_API_TOKEN:-}" ]]; then
    log "ABORT: neither ANTHROPIC_API_KEY nor AGENT_API_TOKEN is set"
    ok=1
  elif [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    log "credentials will be fetched from app at run time"
  fi
  [[ -x "$DAILY_APPLY" ]] || { log "ABORT: $DAILY_APPLY missing or not executable"; ok=1; }
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
      target=$(date -d "$(date -d "@$now" +%F) +${offset} days ${t}" +%s 2>/dev/null) || return 1
      dow=$(date -d "@$target" +%u)
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
  local at days
  at="$(node "$AGENT_CONFIG_JS" run_at 2>/dev/null)" || at=""
  days="$(node "$AGENT_CONFIG_JS" run_days 2>/dev/null)" || days=""
  RUN_AT="${at:-$RUN_AT_DEFAULT}"
  RUN_DAYS="${days:-$RUN_DAYS_DEFAULT}"
  SCHEDULE_SOURCE=config
  [[ -n "$at" ]] || SCHEDULE_SOURCE=env
  validate_run_at || { RUN_AT="$RUN_AT_DEFAULT"; RUN_DAYS="$RUN_DAYS_DEFAULT"; SCHEDULE_SOURCE=env; }
}

# Print the next few slots and exit, so the schedule can be checked without
# waiting a day for it. Deliberately runs BEFORE preflight: it submits
# nothing (it only reads the schedule via refresh_schedule), so it must not
# require ANTHROPIC_API_KEY.
check_schedule() {
  local cursor secs i
  cursor=$(date +%s)
  refresh_schedule
  validate_run_at || return 1
  echo "RUN_AT=$RUN_AT RUN_DAYS=$RUN_DAYS TZ=${TZ:-unset} source=$SCHEDULE_SOURCE - next ${CHECK_SLOTS:-6} slots:"
  for (( i = 0; i < ${CHECK_SLOTS:-6}; i++ )); do
    secs=$(seconds_until_next_slot "$cursor") || return 1
    cursor=$(( cursor + secs ))
    date -d "@$cursor" '+  %a %Y-%m-%d %H:%M %Z'
  done
  return 0
}

# --- Main --------------------------------------------------------------------
if [[ "${1:-}" == "--check-schedule" ]]; then
  check_schedule
  exit $?
fi

log "agent starting (TZ=${TZ:-unset}, RUN_AT=$RUN_AT, RUN_DAYS=$RUN_DAYS)"

preflight || exit 1

if [[ "${RUN_ONCE:-0}" == "1" ]]; then
  log "RUN_ONCE set - running immediately"
  do_run
  exit $?
fi

while true; do
  refresh_schedule
  if ! secs=$(seconds_until_next_slot); then
    log "ERROR: could not compute next slot from RUN_AT=$RUN_AT RUN_DAYS=$RUN_DAYS"
    exit 1
  fi
  if (( secs > 300 )); then
    sleep 300
    continue          # re-fetch and recompute; the slot may have moved
  fi
  log "next run in ${secs}s ($(date -d "@$(( $(date +%s) + secs ))" '+%a %Y-%m-%d %H:%M %Z'))"
  sleep "$secs"
  do_run || log "run failed; continuing to next slot"
done
