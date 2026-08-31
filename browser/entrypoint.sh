#!/usr/bin/env bash
# Browser container entrypoint: starts Xvfb, x11vnc, noVNC, and @playwright/mcp.
# Ported from agent/entrypoint.sh's log() idiom and startup pattern.

set -uo pipefail

# Defaults (override via environment)
DISPLAY="${DISPLAY:-:99}"
XVFB_SIZE="${XVFB_SIZE:-1920x1080x24}"
BROWSER_MCP_PORT="${BROWSER_MCP_PORT:-8931}"
BROWSER_MCP_HOST="${BROWSER_MCP_HOST:-0.0.0.0}"
BROWSER_PROFILE_DIR="${BROWSER_PROFILE_DIR:-/browser-profile}"
BROWSER_VIEWPORT_SIZE="${BROWSER_VIEWPORT_SIZE:-1920,1080}"
# @playwright/mcp rejects requests whose Host header is not in its allowlist
# (DNS-rebinding protection). It defaults to the bind host, so with
# --host 0.0.0.0 every cross-container request to http://browser:8931 comes
# back 403. The agent reaches this service by its compose service name, so
# that name must be listed here.
BROWSER_ALLOWED_HOSTS="${BROWSER_ALLOWED_HOSTS:-browser:${BROWSER_MCP_PORT},localhost:${BROWSER_MCP_PORT}}"
NOVNC_PORT="${NOVNC_PORT:-7900}"

# Logging helper (match agent/entrypoint.sh style)
log() {
  printf '%s  %s\n' "$(date +%H:%M:%S)" "$*"
}

abort() {
  log "ABORT: $*"
  exit 1
}

log "=== browser container starting (DISPLAY=$DISPLAY) ==="

# Clear a stale X lock before starting Xvfb.
#
# Xvfb refuses a display whose /tmp/.X<n>-lock names a pid that is alive
# ("Fatal server error: Server is already active for display 99"), and that
# file lives in the container's own writable layer — it survives the
# `restart: unless-stopped` restart that the X server which wrote it does not.
# Pids start again from 1 in the restarted container, so the recorded pid is
# routinely occupied by an unrelated process and Xvfb's liveness test reports
# a display nothing is serving as held. The entrypoint then aborts, Docker
# restarts it, and it reads the same stale lock: an unattended crash loop that
# takes the noVNC viewport and @playwright/mcp down with it, ending only if the
# pid happens not to be reused on some later attempt.
#
# Adjudicated rather than deleted unconditionally, in the same spirit as the
# SingletonLock handling further down: the lock is cleared only when nothing
# that could actually be an X server holds that pid. A real server still wins,
# and Xvfb still gets to refuse.
display_num="${DISPLAY#:}"
display_num="${display_num%%.*}"
x_lock="/tmp/.X${display_num}-lock"
if [[ -e "$x_lock" ]]; then
  # The lock's sole contents are the X server's pid, space-padded.
  lock_pid="$(tr -dc '0-9' < "$x_lock" 2>/dev/null || true)"
  lock_holder=""
  if [[ -n "$lock_pid" ]] && kill -0 "$lock_pid" 2>/dev/null; then
    lock_holder="$(cat "/proc/$lock_pid/comm" 2>/dev/null || true)"
  fi
  case "$lock_holder" in
    Xvfb|Xorg|X)
      log "display $DISPLAY is already served by $lock_holder (pid $lock_pid) — leaving $x_lock alone"
      ;;
    *)
      if [[ -n "$lock_holder" ]]; then
        log "clearing stale $x_lock: pid $lock_pid is $lock_holder, not an X server"
      else
        log "clearing stale $x_lock (pid '${lock_pid:-unreadable}' is not running)"
      fi
      # The socket is the lock's other half: Xvfb recreates it, but leaving a
      # dead one behind lets a client connect to nothing.
      rm -f "$x_lock" "/tmp/.X11-unix/X${display_num}"
      ;;
  esac
fi

# Start Xvfb (virtual X11 server)
log "starting Xvfb on $DISPLAY with size $XVFB_SIZE..."
Xvfb "$DISPLAY" -screen 0 "$XVFB_SIZE" &
XVFB_PID=$!
sleep 2  # Give Xvfb time to start

# Verify Xvfb started
if ! kill -0 "$XVFB_PID" 2>/dev/null; then
  abort "Xvfb failed to start (PID $XVFB_PID)"
fi
log "Xvfb running on PID $XVFB_PID"

# Start x11vnc (VNC server against the Xvfb display)
# -forever: without it x11vnc exits the moment the first viewer disconnects,
# and every later viewport connection fails with websockify refusing on
# localhost:5900 — the operator sees "could not connect to the browser" for
# the rest of the container's life. The viewport is opened and closed once
# per attended sign-in, so serving exactly one viewer is never what we want.
# -shared: a reconnect (the page's Reload, or a second tab) attaches
# alongside the old socket instead of disconnecting it.
log "starting x11vnc on $DISPLAY..."
export DISPLAY
x11vnc -display "$DISPLAY" -nopw -xkb -forever -shared -o /tmp/x11vnc.log 2>&1 &
X11VNC_PID=$!
sleep 1

if ! kill -0 "$X11VNC_PID" 2>/dev/null; then
  abort "x11vnc failed to start (PID $X11VNC_PID)"
fi
log "x11vnc running on PID $X11VNC_PID"

# Start the window manager. Chromium's windows are unmanaged without one, and
# an SSO popup then cannot be raised, moved or closed from the viewport.
log "starting openbox on $DISPLAY..."
openbox &
OPENBOX_PID=$!
sleep 1

if ! kill -0 "$OPENBOX_PID" 2>/dev/null; then
  abort "openbox failed to start (PID $OPENBOX_PID)"
fi
log "openbox running on PID $OPENBOX_PID"

# Start noVNC / websockify (web-based VNC at http://localhost:7900)
log "starting noVNC on port $NOVNC_PORT..."
# Ubuntu's novnc package ships only the web assets (/usr/share/novnc),
# no launcher binary — websockify serves them and bridges to x11vnc.
websockify --web=/usr/share/novnc "$NOVNC_PORT" localhost:5900 >/tmp/novnc.log 2>&1 &
NOVNC_PID=$!
sleep 1

if ! kill -0 "$NOVNC_PID" 2>/dev/null; then
  abort "noVNC failed to start (PID $NOVNC_PID)"
fi
log "noVNC running on PID $NOVNC_PID (http://localhost:$NOVNC_PORT)"

# Start @playwright/mcp
# --browser chromium: use Chromium (shipped by the playwright base image)
# --port / --host: HTTP transport (not stdio)
# --user-data-dir: persistent profile (mounted at /browser-profile)
# --viewport-size: browser window size
# DISPLAY must be set for Chromium to run headful under Xvfb
# Chromium refuses to start on a profile whose SingletonLock it cannot
# attribute. The lock is a symlink named "<hostname>-<pid>", and the profile is
# a persistent volume: a container RECREATED after an unclean stop gets a new
# hostname, so the old lock matches nothing Chromium can check and it gives up
# — surfacing through @playwright/mcp as "Browser is already in use for
# <profile>" on every navigate, for the life of the volume.
#
# Only that case is cleared, and only after checking. Chromium already breaks a
# stale lock itself when the hostname matches and the pid is dead — which is
# the common restart path, since `restart: unless-stopped` keeps the hostname —
# so deleting unconditionally would throw away the one artefact that
# distinguishes a stale lock from a live holder the next time this breaks for a
# different reason. Nothing else mounts this volume today (docker-compose.yml
# declares browser-profile with a single mount), but that is a fact about the
# current compose file, not an invariant this script should assume.
#
# SingletonCookie and SingletonSocket do not gate startup and are left alone.
lock_path="$BROWSER_PROFILE_DIR/SingletonLock"
if [[ -L "$lock_path" ]]; then
  lock_target="$(readlink "$lock_path" 2>/dev/null || true)"
  lock_host="${lock_target%-*}"
  lock_pid="${lock_target##*-}"
  if [[ -z "$lock_target" ]]; then
    log "SingletonLock is unreadable — leaving it for Chromium to adjudicate"
  elif [[ "$lock_host" != "$(hostname)" ]]; then
    log "clearing SingletonLock from a previous container ($lock_target; this host is $(hostname))"
    rm -f "$lock_path"
  elif [[ "$lock_pid" =~ ^[0-9]+$ ]] && ! kill -0 "$lock_pid" 2>/dev/null; then
    log "clearing SingletonLock held by dead pid $lock_pid on this host"
    rm -f "$lock_path"
  else
    log "SingletonLock ($lock_target) looks live — leaving it alone"
  fi
fi

# Start the attended session control server (see browser/session-server.js).
# Started here, after the SingletonLock adjudication above rather than before
# it: a POST /session arriving in that window would launch Chromium against a
# lock the entrypoint was about to clear.
log "starting session server on port ${SESSION_SERVER_PORT:-8932}..."
node /browser/session-server.js &
SESSION_PID=$!
sleep 1

if ! kill -0 "$SESSION_PID" 2>/dev/null; then
  abort "session server failed to start (PID $SESSION_PID)"
fi
log "session server running on PID $SESSION_PID"

# @playwright/mcp@0.0.79's file-access sandbox (playwright-core's checkFile)
# only allows a resolved path through when it falls under EITHER its
# --output-dir OR the MCP client's first advertised "root" (via the client
# capability/roots protocol, exposed here as clientInfo.cwd). Our agent's HTTP
# JSON-RPC client does not implement that roots capability, so clientInfo.cwd
# is empty and --output-dir is the only lever available. `--help` (0.0.79)
# describes the two relevant options as:
#
#   --allow-unrestricted-file-access      allow access to files outside of the
#                                          workspace roots. Also allows
#                                          unrestricted access to file:// URLs.
#                                          By default access to file system is
#                                          restricted to workspace root
#                                          directories (or cwd if no roots are
#                                          configured) only, and navigation to
#                                          file:// URLs is blocked.
#   --output-dir <path>                   path to the directory for output
#                                          files.
#
# There is no explicit allow-list/roots flag in this version — --output-dir is
# it. --allow-unrestricted-file-access would also work but disables the
# sandbox entirely, which is more than this needs. Pointing --output-dir at
# /app (not /app/data, which is mounted read-only and must stay writable-free)
# makes /app/data reachable as a subdirectory of the allowed root without
# widening access past the app's own tree.
BROWSER_UPLOAD_ROOT_DIR="${BROWSER_UPLOAD_ROOT_DIR:-/app}"
log "playwright/mcp upload/output root: $BROWSER_UPLOAD_ROOT_DIR (covers /app/data)"

log "starting @playwright/mcp on port $BROWSER_MCP_PORT..."
exec env DISPLAY="$DISPLAY" \
  npx @playwright/mcp@0.0.79 \
    --browser chromium \
    --port "$BROWSER_MCP_PORT" \
    --host "$BROWSER_MCP_HOST" \
    --user-data-dir "$BROWSER_PROFILE_DIR" \
    --viewport-size "$BROWSER_VIEWPORT_SIZE" \
    --allowed-hosts "$BROWSER_ALLOWED_HOSTS" \
    --output-dir "$BROWSER_UPLOAD_ROOT_DIR"
