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
log "starting x11vnc on $DISPLAY..."
export DISPLAY
x11vnc -display "$DISPLAY" -nopw -xkb -o /tmp/x11vnc.log 2>&1 &
X11VNC_PID=$!
sleep 1

if ! kill -0 "$X11VNC_PID" 2>/dev/null; then
  abort "x11vnc failed to start (PID $X11VNC_PID)"
fi
log "x11vnc running on PID $X11VNC_PID"

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
# Chromium writes SingletonLock/Cookie/Socket into the profile and names them
# after the host and PID that hold it. The profile is a persistent volume but
# the container's hostname changes on every recreate, so a container that was
# killed rather than shut down cleanly leaves a lock Chromium can no longer
# attribute — and refuses to start on. @playwright/mcp surfaces that as
# "Browser is already in use for <profile>" on every navigate, for the life of
# the volume. Nothing can legitimately hold the profile at container start, so
# clearing them here is safe and is the only point at which that is true.
for singleton in SingletonLock SingletonCookie SingletonSocket; do
  if [[ -e "$BROWSER_PROFILE_DIR/$singleton" || -L "$BROWSER_PROFILE_DIR/$singleton" ]]; then
    log "clearing stale $singleton in $BROWSER_PROFILE_DIR"
    rm -f "$BROWSER_PROFILE_DIR/$singleton"
  fi
done

log "starting @playwright/mcp on port $BROWSER_MCP_PORT..."
exec env DISPLAY="$DISPLAY" \
  npx @playwright/mcp \
    --browser chromium \
    --port "$BROWSER_MCP_PORT" \
    --host "$BROWSER_MCP_HOST" \
    --user-data-dir "$BROWSER_PROFILE_DIR" \
    --viewport-size "$BROWSER_VIEWPORT_SIZE" \
    --allowed-hosts "$BROWSER_ALLOWED_HOSTS"
