#!/usr/bin/env bash
# Smoke test for TruthCV's unattended agent container. Verifies the agent's
# wiring WITHOUT applying to anything: it submits nothing, writes no
# application record, and never touches an employer site.
#
# Run it against the built image:
#   docker compose --profile agent run --rm \
#     --entrypoint /app/agent/smoke-test.sh agent
#
# Ported from the retiring Jobs project's docker/smoke-test.sh, but the checks
# are necessarily different: that image contained its own Chrome under Xvfb and
# its smoke test verified the browser stack. THIS image contains no browser at
# all on purpose (agent/Dockerfile, BROWSER STRATEGY) - the browser lives in the
# sibling `browser` compose service - so the equivalent question here is
# whether that service and the MCP tool surface are actually reachable from
# inside.
set -uo pipefail

pass=0; fail=0
ok()  { echo "  PASS  $*"; pass=$((pass+1)); }
bad() { echo "  FAIL  $*"; fail=$((fail+1)); }

AGENT_DIR="${AGENT_DIR:-/app/agent}"
RUN_LOG_DIR="${RUN_LOG_DIR:-/app/runs}"
BROWSER_MCP_URL="${BROWSER_MCP_URL:-http://browser:8931/mcp}"

echo "== truthcv agent smoke test =="

# --- The image itself --------------------------------------------------------

if command -v claude >/dev/null 2>&1; then
  ok "claude CLI present ($(claude --version 2>/dev/null | head -1))"
else
  bad "claude CLI missing - daily-apply.sh aborts without it"
fi

# node ships with the base image (node:22-bookworm-slim) and is what the
# HTTP probes below are written in: this image installs no curl, nc or
# socat, so node is the only thing here that can open a connection.
command -v node >/dev/null 2>&1 \
  && ok "node present (used by the reachability probes below)" \
  || bad "node missing - the probes below cannot run"

command -v jq >/dev/null 2>&1 \
  && ok "jq present" \
  || bad "jq missing - daily-apply.sh aborts without it"

# The absence of a browser is a DELIBERATE property of this image, not an
# oversight, so it is pinned here: if someone re-adds Chrome/Chromium/
# Playwright, this test should turn red and make them justify it. The
# browser lives in its own `browser` compose service by design, so finding
# one in the agent image would mean the images got crossed.
browsers=""
for b in google-chrome google-chrome-stable chromium chromium-browser Xvfb playwright; do
  command -v "$b" >/dev/null 2>&1 && browsers="$browsers $b"
done
[[ -z "$browsers" ]] \
  && ok "no in-container browser, as intended (it lives in the browser service)" \
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
  if (!s.truthcv || !s.browser) { process.exit(1); }
' 2>/dev/null; then
  ok "mcp.json is valid JSON and declares the truthcv + browser servers"
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

# This only proves the `browser` compose service is accepting connections and
# speaking HTTP, NOT that the MCP session handshake succeeds - do NOT check
# the status code here. MCP's streamable-HTTP transport answers a bare GET
# (no session id, no `Accept: text/event-stream` header) with a 4xx - 400,
# 405 or 406 - BY DESIGN, so a healthy server will never return 200 to this
# probe. Only a connection error or a timeout means unreachable.
if node -e '
  const url = process.argv[1];
  const mod = url.startsWith("https:") ? require("https") : require("http");
  const req = mod.get(url, { timeout: 5000 }, () => process.exit(0));
  req.on("timeout", () => { req.destroy(); process.exit(1); });
  req.on("error", () => process.exit(1));
' "$BROWSER_MCP_URL" 2>/dev/null; then
  ok "BROWSER_MCP_URL reachable ($BROWSER_MCP_URL)"
else
  bad "BROWSER_MCP_URL unreachable ($BROWSER_MCP_URL) - check docker compose ps browser / docker compose logs browser"
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
