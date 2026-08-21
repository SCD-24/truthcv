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
# all on purpose (agent/Dockerfile, BROWSER STRATEGY) - the browser lives on
# the host - so the equivalent question here is whether the socket to the host
# browser and the MCP tool surface are actually reachable from inside.
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

# jq renders the job-profile / criteria / salary prompt block in daily-apply.sh
command -v jq >/dev/null 2>&1 \
  && ok "jq present (used by daily-apply.sh to render the profile prompt block)" \
  || bad "jq missing - daily-apply.sh's profile rendering will fail"

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

if [[ -n "${TRUTHCV_MCP_URL:-}" ]]; then
  if node -e '
    const u = new URL(process.env.TRUTHCV_MCP_URL);
    const http = require(u.protocol === "https:" ? "https" : "http");
    
    function makeRequest(method, payload) {
      return new Promise((resolve, reject) => {
        const req = http.request(u, {
          method,
          headers: {
            "Content-Type": "application/json",
            "accept": "application/json, text/event-stream"
          },
          timeout: 5000
        }, (res) => {
          let data = "";
          res.on("data", (chunk) => { data += chunk; });
          res.on("end", () => {
            if (res.statusCode === 307 || res.statusCode === 308) {
              reject(new Error(`Redirect ${res.statusCode} to ${res.headers.location}`));
            } else if (res.statusCode >= 400) {
              reject(new Error(`HTTP ${res.statusCode}`));
            } else {
              resolve(data);
            }
          });
        });
        req.on("error", reject);
        req.on("timeout", () => {
          req.destroy();
          reject(new Error("timeout"));
        });
        if (payload) {
          req.write(JSON.stringify(payload));
        }
        req.end();
      });
    }
    
    (async () => {
      try {
        // Initialize handshake
        const initResp = await makeRequest("POST", {
          jsonrpc: "2.0",
          id: 1,
          method: "initialize",
          params: {
            protocolVersion: "2024-11-05",
            capabilities: {},
            clientInfo: { name: "smoke-test", version: "1.0" }
          }
        });
        const init = JSON.parse(initResp);
        if (!init.result && !init.error) {
          throw new Error("not JSON-RPC format");
        }
        
        // Send notifications/initialized
        await makeRequest("POST", {
          jsonrpc: "2.0",
          method: "notifications/initialized",
          params: {}
        });
        
        // List tools
        const toolsResp = await makeRequest("POST", {
          jsonrpc: "2.0",
          id: 2,
          method: "tools/list",
          params: {}
        });
        const tools = JSON.parse(toolsResp);
        if (!tools.result || !tools.result.tools) {
          throw new Error("no tools in result");
        }
        
        const toolList = tools.result.tools.map(t => t.name);
        const expectedTools = [
          "check_cooldown", "generate_cover_letter", "get_canonical_cv",
          "get_job_profiles", "get_profile_answers", "recommend_salary",
          "record_application", "record_company_board", "record_screening"
        ].sort();
        const actualTools = toolList.sort();
        
        if (JSON.stringify(expectedTools) !== JSON.stringify(actualTools)) {
          throw new Error(`wrong tools: ${actualTools.join(", ")}`);
        }
        
        console.log(actualTools.join(", "));
        process.exit(0);
      } catch (e) {
        process.exit(1);
      }
    })();
  ' 2>&1; then
    tools=$?
    if [[ "$tools" != "0" ]]; then
      # Re-run to capture tool list for display
      tool_list=$(node -e '
        const u = new URL(process.env.TRUTHCV_MCP_URL);
        const http = require(u.protocol === "https:" ? "https" : "http");
        function makeRequest(method, payload) {
          return new Promise((resolve, reject) => {
            const req = http.request(u, {
              method, headers: { "Content-Type": "application/json" },
              timeout: 5000
            }, (res) => {
              let data = "";
              res.on("data", (chunk) => { data += chunk; });
              res.on("end", () => { resolve(data); });
            });
            req.on("error", reject);
            req.on("timeout", () => { req.destroy(); reject(); });
            if (payload) req.write(JSON.stringify(payload));
            req.end();
          });
        }
        (async () => {
          try {
            const initResp = await makeRequest("POST", { jsonrpc: "2.0", id: 1, method: "initialize", params: {} });
            await makeRequest("POST", { jsonrpc: "2.0", method: "notifications/initialized", params: {} });
            const toolsResp = await makeRequest("POST", { jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
            const tools = JSON.parse(toolsResp);
            console.log(tools.result.tools.map(t => t.name).sort().join(", "));
          } catch (e) { process.exit(1); }
        })();
      ' 2>/dev/null)
      ok "TRUTHCV_MCP_URL JSON-RPC handshake successful ($TRUTHCV_MCP_URL)"
      echo "        Tools: $tool_list"
    else
      bad "TRUTHCV_MCP_URL JSON-RPC handshake failed - endpoint does not speak MCP JSON-RPC"
    fi
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
