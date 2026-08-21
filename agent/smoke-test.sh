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

# jq renders the job-profile / criteria / salary prompt block in daily-apply.sh
command -v jq >/dev/null 2>&1 \
  && ok "jq present (used by daily-apply.sh to render the profile prompt block)" \
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

# A bare GET here would prove nothing: the app serves an SPA catch-all, so every
# URL under it answers 200 and the old probe passed while all nine tools failed
# to register. Do the real MCP handshake instead - initialize, initialized,
# tools/list - and insist on the nine tools by name.
if [[ -n "${TRUTHCV_MCP_URL:-}" ]]; then
  if MCP_OUT="$(node -e '
    const u = new URL(process.env.TRUTHCV_MCP_URL);
    const http = require(u.protocol === "https:" ? "https" : "http");
    let sessionId = null;

    // The streamable-HTTP transport may answer as application/json OR as
    // text/event-stream depending on how the server was configured, so accept
    // both and unwrap SSE by taking the last data: line.
    function parseBody(body, contentType) {
      if ((contentType || "").includes("text/event-stream")) {
        const data = body.split(/\r?\n/)
          .filter((l) => l.startsWith("data:"))
          .map((l) => l.slice(5).trim());
        if (!data.length) throw new Error("SSE response carried no data: line");
        return JSON.parse(data[data.length - 1]);
      }
      return JSON.parse(body);
    }

    function rpc(payload) {
      return new Promise((resolve, reject) => {
        const headers = {
          "content-type": "application/json",
          // Required by the streamable-HTTP transport.
          "accept": "application/json, text/event-stream",
        };
        if (sessionId) headers["mcp-session-id"] = sessionId;
        const req = http.request(u, { method: "POST", headers, timeout: 5000 }, (res) => {
          let body = "";
          res.on("data", (c) => { body += c; });
          res.on("end", () => {
            // Never follow a redirect: if the endpoint sits behind a Starlette
            // Mount, POST /mcp 307s to /mcp/ and following it would hide exactly
            // that trap.
            if (res.statusCode >= 300 && res.statusCode < 400) {
              return reject(new Error("HTTP " + res.statusCode + " redirect to " +
                (res.headers.location || "(no Location)") + " - not followed"));
            }
            if (res.statusCode === 405) {
              return reject(new Error("HTTP 405 - the URL is a plain-REST router, " +
                "not an MCP JSON-RPC endpoint"));
            }
            if (res.statusCode >= 400) {
              return reject(new Error("HTTP " + res.statusCode + ": " + body.slice(0, 200)));
            }
            if (res.headers["mcp-session-id"]) sessionId = res.headers["mcp-session-id"];
            if (!body.trim()) return resolve(null);
            try {
              resolve(parseBody(body, res.headers["content-type"]));
            } catch (e) {
              reject(new Error("response is not JSON-RPC: " + e.message));
            }
          });
        });
        req.on("error", (e) => reject(new Error(e.message)));
        req.on("timeout", () => { req.destroy(); reject(new Error("timeout after 5000ms")); });
        req.end(JSON.stringify(payload));
      });
    }

    const EXPECTED = [
      "check_cooldown", "generate_cover_letter", "get_canonical_cv",
      "get_job_profiles", "get_profile_answers", "recommend_salary",
      "record_application", "record_company_board", "record_screening",
    ].sort();

    (async () => {
      const init = await rpc({
        jsonrpc: "2.0", id: 1, method: "initialize",
        params: {
          protocolVersion: "2024-11-05",
          capabilities: {},
          clientInfo: { name: "truthcv-smoke-test", version: "1.0" },
        },
      });
      if (!init || !init.result) {
        throw new Error("initialize did not return a JSON-RPC result");
      }
      await rpc({ jsonrpc: "2.0", method: "notifications/initialized", params: {} });

      const listed = await rpc({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
      if (!listed || !listed.result || !Array.isArray(listed.result.tools)) {
        throw new Error("tools/list did not return a tools array");
      }
      const names = listed.result.tools.map((t) => t.name).sort();
      const missing = EXPECTED.filter((n) => !names.includes(n));
      if (missing.length) {
        throw new Error("missing tool(s): " + missing.join(", ") +
          " (got " + (names.length ? names.join(", ") : "none") + ")");
      }
      console.log(names.join(", "));
    })().catch((e) => { console.error(e.message); process.exit(1); });
  ' 2>&1)"; then
    ok "TRUTHCV_MCP_URL MCP handshake OK ($TRUTHCV_MCP_URL)"
    echo "   tools: $MCP_OUT"
  else
    bad "TRUTHCV_MCP_URL MCP handshake failed ($TRUTHCV_MCP_URL) - $MCP_OUT"
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
