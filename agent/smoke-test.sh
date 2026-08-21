#!/usr/bin/env bash
# Smoke test for TruthCV's unattended agent container. Verifies the agent's
# wiring WITHOUT applying to anything: it submits nothing, writes no
# application record, and never touches an employer site.
#
# Run it against the built image:
#   docker compose --profile agent run --rm \
#     --entrypoint /app/agent/smoke-test.sh agent
#
# Verifies that the `claude` CLI spawns `interceptor mcp serve` over stdio in-container,
# and that subprocess shells to the real `interceptor <verb>` command (the bind-mounted
# Bun binary) to reach the host interceptor daemon over the bind-mounted unix socket.
# The daemon reaches Chrome via native messaging. This chain must be solid end-to-end:
# if the binary is missing/incompatible with the container's glibc, or if the socket
# is stale/dead, those failures surface here, where they belong, not mid-run.
set -uo pipefail

pass=0; fail=0
ok()  { echo "  PASS  $*"; pass=$((pass+1)); }
bad() { echo "  FAIL  $*"; fail=$((fail+1)); }

AGENT_DIR="${AGENT_DIR:-/app/agent}"
RUN_LOG_DIR="${RUN_LOG_DIR:-/app/runs}"
INTERCEPTOR_SOCKET="${INTERCEPTOR_SOCKET:-/tmp/interceptor.sock}"

echo "== truthcv agent smoke test =="

# --- The image itself --------------------------------------------------------

if command -v claude >/dev/null 2>&1; then
  ok "claude CLI present ($(claude --version 2>/dev/null | head -1))"
else
  bad "claude CLI missing - daily-apply.sh aborts without it"
fi

# node ships with the base image (node:22-bookworm-slim) and is what the
# socket and HTTP probes below are written in: this image installs no curl,
# nc or socat, so node is the only thing here that can open a connection.
command -v node >/dev/null 2>&1 \
  && ok "node present (used by the reachability probes below)" \
  || bad "node missing - the probes below cannot run"

# The absence of a browser is a DELIBERATE property of this image, not an
# oversight, so it is pinned here: if someone re-adds Chrome/Chromium/
# Playwright, this test should turn red and make them justify it.
browsers=""
for b in google-chrome google-chrome-stable chromium chromium-browser Xvfb playwright; do
  command -v "$b" >/dev/null 2>&1 && browsers="$browsers $b"
done
[[ -z "$browsers" ]] \
  && ok "no in-container browser, as intended (host Chrome is the only path)" \
  || bad "in-container browser stack present:$browsers - see agent/Dockerfile"

# --- The agent's own files ---------------------------------------------------

for f in RUNBOOK.md prompt.md mcp.json daily-apply.sh entrypoint.sh; do
  [[ -r "$AGENT_DIR/$f" ]] && ok "$f readable" || bad "$AGENT_DIR/$f missing"
done

for f in daily-apply.sh entrypoint.sh; do
  [[ -x "$AGENT_DIR/$f" ]] || bad "$AGENT_DIR/$f not executable"
  bash -n "$AGENT_DIR/$f" 2>/dev/null && ok "$f parses" || bad "$f has a syntax error"
done

if node -e '
  const c = require("'"$AGENT_DIR"'/mcp.json");
  const s = c.mcpServers || {};
  if (!s.truthcv || !s.interceptor) { process.exit(1); }
' 2>/dev/null; then
  ok "mcp.json is valid JSON and declares the truthcv + interceptor servers"
else
  bad "mcp.json is malformed or missing a server the allow-list names"
fi

# --- The schedule ------------------------------------------------------------

slots=$("$AGENT_DIR/entrypoint.sh" --check-schedule 2>&1)
if [[ $? -eq 0 ]] && [[ $(echo "$slots" | grep -c ':') -gt 1 ]]; then
  ok "schedule resolves (RUN_AT=${RUN_AT:-unset})"
  echo "$slots" | sed 's/^/        /'
else
  bad "--check-schedule failed: $slots"
fi

# --- Reachability ------------------------------------------------------------

# A present socket FILE proves only that the bind mount worked; a stale socket
# left by a dead interceptor daemon looks identical. daily-apply.sh can only
# check the file, so this connects to it - the difference between "the mount is
# there" and "the host browser can actually be driven".
if [[ -S "$INTERCEPTOR_SOCKET" ]]; then
  ok "interceptor socket bind-mounted at $INTERCEPTOR_SOCKET"
  if node -e '
    const net = require("net");
    const s = net.connect("'"$INTERCEPTOR_SOCKET"'");
    s.on("connect", () => { s.end(); process.exit(0); });
    s.on("error", () => process.exit(1));
    setTimeout(() => process.exit(1), 3000);
  ' 2>/dev/null; then
    ok "interceptor socket accepts a connection (daemon alive on the host)"
  else
    bad "interceptor socket is present but dead - the host daemon is not listening"
  fi
else
  bad "no socket at $INTERCEPTOR_SOCKET - start the host interceptor daemon"
fi

# --- Interceptor binary chain ------------------------------------------------

INTERCEPTOR_BIN="${INTERCEPTOR_BIN:-/opt/interceptor/bin/interceptor}"

if [[ -x "$INTERCEPTOR_BIN" ]]; then
  ok "interceptor binary exists and is executable ($INTERCEPTOR_BIN)"
  
  # The binary is Bun-compiled on the host and must run under the container's
  # glibc — if there's a version mismatch, the loader will fail with a message
  # like "version GLIBC_2.36 not found". That's our most likely failure mode.
  binary_output=$("$INTERCEPTOR_BIN" 2>&1 | head -20)
  if echo "$binary_output" | grep -q "version GLIBC_.*not found"; then
    bad "interceptor binary glibc incompatibility: $(echo "$binary_output" | grep "version GLIBC_")"
    bad "  This means the host's Bun-compiled binary needs glibc from the host — try the fallback: a host-side stdio→HTTP shim"
  else
    ok "interceptor binary runs in this container (no loader/glibc error)"
  fi
  
  # Spawn the MCP server and verify it starts up correctly.
  server_output=$(timeout 3 "$INTERCEPTOR_BIN" mcp serve 2>&1 || true)
  if echo "$server_output" | grep -q "serving over stdio"; then
    ok "interceptor mcp serve starts and announces stdio readiness"
  else
    bad "interceptor mcp serve did not emit 'serving over stdio' on startup"
    [[ -n "$server_output" ]] && echo "    Server output: $server_output" >&2
  fi
else
  bad "interceptor binary not executable or missing at $INTERCEPTOR_BIN"
fi

# --- mcp.json validation -----------------------------------------------

if jq . "$AGENT_DIR/mcp.json" >/dev/null 2>&1; then
  if jq '.mcpServers.interceptor.args' "$AGENT_DIR/mcp.json" | grep -q '"mcp"'; then
    if ! grep -q "interceptor-mcp" "$AGENT_DIR/mcp.json"; then
      ok "mcp.json interceptor entry: command removed, args set to [\"mcp\",\"serve\"], no old \"interceptor-mcp\" string"
    else
      bad "mcp.json still contains the string 'interceptor-mcp' — update to the real command"
    fi
  else
    bad "mcp.json interceptor args are not [\"mcp\",\"serve\"]"
  fi
else
  bad "mcp.json is not valid JSON"
fi

if [[ -n "${TRUTHCV_MCP_URL:-}" ]]; then
  if node -e '
    const u = new URL(process.env.TRUTHCV_MCP_URL);
    const http = require(u.protocol === "https:" ? "https" : "http");
    const r = http.request(u, { method: "GET", timeout: 5000 }, () => process.exit(0));
    r.on("error", () => process.exit(1));
    r.on("timeout", () => process.exit(1));
    r.end();
  ' 2>/dev/null; then
    ok "TRUTHCV_MCP_URL reachable ($TRUTHCV_MCP_URL)"
  else
    bad "TRUTHCV_MCP_URL set but unreachable ($TRUTHCV_MCP_URL) - is the app service up?"
  fi
else
  bad "TRUTHCV_MCP_URL is not set - the agent has no route to the TruthCV tools"
fi

# --- Run logs ----------------------------------------------------------------

if mkdir -p "$RUN_LOG_DIR" 2>/dev/null && touch "$RUN_LOG_DIR/.smoke" 2>/dev/null; then
  rm -f "$RUN_LOG_DIR/.smoke"
  ok "run log dir writable ($RUN_LOG_DIR)"
else
  bad "run log dir not writable ($RUN_LOG_DIR) - runs will lose their logs"
fi

echo "== $pass passed, $fail failed =="
exit $(( fail > 0 ))
