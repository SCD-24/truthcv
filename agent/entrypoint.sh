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
# and RUN_DAYS (comma-separated 1=Mon .. 7=Sun). docker-compose.yml defaults
# RUN_AT to "09:00,15:00" - two runs a day is the configured cadence, and
# that default is mirrored by AGENT_RUN_TIMES in
# web/src/settings/SettingsModal.tsx, which the Settings UI displays as the
# schedule. If you change one, change the other.

set -uo pipefail

RUN_AT="${RUN_AT:-09:00,15:00}"
RUN_DAYS="${RUN_DAYS:-1,2,3,4,5}"
DAILY_APPLY="${DAILY_APPLY:-/app/agent/daily-apply.sh}"

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
  [[ -n "${ANTHROPIC_API_KEY:-}" ]] || { log "ABORT: ANTHROPIC_API_KEY is not set"; ok=1; }
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
      target=$(date -d "today +${offset} days ${t}" +%s 2>/dev/null) || return 1
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

# Print the next few slots and exit, so the schedule can be checked without
# waiting a day for it. Deliberately runs BEFORE preflight: it submits
# nothing and talks to nothing, so it must not require ANTHROPIC_API_KEY.
check_schedule() {
  local cursor secs i
  cursor=$(date +%s)
  validate_run_at || return 1
  echo "RUN_AT=$RUN_AT RUN_DAYS=$RUN_DAYS TZ=${TZ:-unset} - next ${CHECK_SLOTS:-6} slots:"
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
  if ! secs=$(seconds_until_next_slot); then
    log "ERROR: could not compute next slot from RUN_AT=$RUN_AT RUN_DAYS=$RUN_DAYS"
    exit 1
  fi
  log "next run in ${secs}s ($(date -d "@$(( $(date +%s) + secs ))" '+%a %Y-%m-%d %H:%M %Z'))"
  sleep "$secs"
  do_run || log "run failed; continuing to next slot"
done
