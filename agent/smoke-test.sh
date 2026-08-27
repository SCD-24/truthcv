#!/usr/bin/env bash
# Smoke test for TruthCV's unattended agent container. Verifies the agent's
# wiring WITHOUT applying to anything: it submits nothing, writes no
# application record, and never touches an employer site.
#
# Run it against the built image:
#   docker compose run --rm --entrypoint /app/agent/smoke-test.sh agent
#
# Ported from the retiring Jobs project's docker/smoke-test.sh, but the checks
# are necessarily different: that image contained its own Chrome under Xvfb and
# its smoke test verified the browser stack. THIS image contains no browser at
# all on purpose (agent/Dockerfile, BROWSER STRATEGY) - the browser lives
# outside it - so the equivalent question here is whether the browser the agent
# has been pointed at, and the MCP tool surface, are reachable from inside.
#
# `browser` (the only supported AGENT_BROWSER_DRIVER value) is the sibling
# `browser` compose service, checked by dialling its in-network MCP endpoint
# over HTTP.
set -uo pipefail

pass=0; fail=0
ok()  { echo "  PASS  $*"; pass=$((pass+1)); }
bad() { echo "  FAIL  $*"; fail=$((fail+1)); }

AGENT_DIR="${AGENT_DIR:-/app/agent}"
RUN_LOG_DIR="${RUN_LOG_DIR:-/app/runs}"
BROWSER_MCP_URL="${BROWSER_MCP_URL:-http://browser:8931/mcp}"

# Same default as agent/daily-apply.sh and agent/mcp.json, so the smoke test
# cannot pass against a configuration the run path would reject.
AGENT_BROWSER_DRIVER="${AGENT_BROWSER_DRIVER:-browser}"

echo "== truthcv agent smoke test =="
echo "   browser driver: $AGENT_BROWSER_DRIVER"

# --- The image itself --------------------------------------------------------

# The provider-neutral agent harness (agent/harness, compiled to
# dist/harness/cli.js by agent/package.json's `build`) is what daily-apply.sh
# invokes as `node "$HARNESS_CLI" ...` - it replaces the CLI this test used to
# check for. Same default path as daily-apply.sh's HARNESS_CLI, so the smoke
# test cannot pass against an image the run path would reject. The harness has
# no --help / no-op mode, so the meaningful check for a compiled ESM file is
# that it exists, is non-empty, and parses under `node --check`.
HARNESS_CLI="${HARNESS_CLI:-$AGENT_DIR/dist/harness/cli.js}"
if [[ ! -s "$HARNESS_CLI" ]]; then
  bad "agent harness missing - build it with \`npm run build\` in agent/ (daily-apply.sh aborts without $HARNESS_CLI)"
elif node --check "$HARNESS_CLI" 2>/dev/null; then
  ok "agent harness built and parses ($HARNESS_CLI)"
else
  bad "agent harness present but fails node --check ($HARNESS_CLI) - the build output is broken"
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

# --- Supervisor ---------------------------------------------------------------

if [[ -r "$AGENT_DIR/supervisor.js" ]]; then
  ok "supervisor.js present"
else
  bad "$AGENT_DIR/supervisor.js missing"
fi

if node --check "$AGENT_DIR/supervisor.js" 2>/dev/null; then
  ok "supervisor.js parses (node --check)"
else
  bad "supervisor.js has a syntax error"
fi

# Spin up supervisor on an ephemeral port, exercise auth and GET /status,
# then shut it down.  We use a tiny inline node harness so no nc/curl needed.
_SUPER_PORT=19099
_SUPER_TOKEN="smoke-test-token-$$"
AGENT_API_TOKEN="$_SUPER_TOKEN" \
AGENT_CONTROL_PORT="$_SUPER_PORT" \
RUN_ONCE="" \
DAILY_APPLY="/bin/true" \
  node "$AGENT_DIR/supervisor.js" >/tmp/supervisor-smoke.log 2>&1 &
_SUPER_PID=$!

# Give the server a moment to start
sleep 1

if SUPER_TOKEN="$_SUPER_TOKEN" node -e '
  const http = require("http");
  const TOKEN = process.env.SUPER_TOKEN;
  function req(token, path, cb) {
    const opts = {
      hostname: "127.0.0.1", port: '"$_SUPER_PORT"', path, method: "GET",
      headers: token ? { "x-agent-token": token } : {},
    };
    const r = http.request(opts, (res) => { let b=""; res.on("data",(c)=>b+=c); res.on("end",()=>cb(null,res.statusCode,b)); });
    r.on("error", (e) => cb(e));
    r.end();
  }
  // 1) Unauthenticated => 403
  req(null, "/status", (e1, s1) => {
    if (e1 || s1 !== 403) { process.stderr.write("expected 403 without token, got " + (e1||s1) + "\n"); process.exit(1); }
    // 2) Authenticated => 200 with running field
    req(TOKEN, "/status", (e2, s2, body) => {
      if (e2 || s2 !== 200) { process.stderr.write("expected 200 with token, got " + (e2||s2) + "\n"); process.exit(1); }
      let obj;
      try { obj = JSON.parse(body); } catch { process.stderr.write("status not JSON\n"); process.exit(1); }
      if (typeof obj.running !== "boolean") { process.stderr.write("missing running field\n"); process.exit(1); }
      process.exit(0);
    });
  });
' 2>/dev/null; then
  ok "supervisor: unauthenticated -> 403, authenticated GET /status -> JSON with 'running'"
else
  bad "supervisor auth or GET /status check failed (see /tmp/supervisor-smoke.log)"
fi

kill "$_SUPER_PID" 2>/dev/null
wait "$_SUPER_PID" 2>/dev/null

# --- Agent config fetch --------------------------------------------------------

# agent-config.js sits in agent/, whose package.json declares "type": "module",
# so node loads it as an ES module and a `require()` inside it is a runtime
# ReferenceError, never a syntax error - `node --check` is structurally unable
# to see that class of defect.  The require sites were inside the two HTTP
# branches, so importing the file was not enough either: the only gate that
# discriminates is to RUN it down both fetch paths.  A stub server on an
# ephemeral port stands in for the app service, so this needs no app, no
# network egress and no curl/nc.
_CFG_PORT=19098
_CFG_TOKEN="smoke-config-token-$$"
_CFG_STUB="/tmp/agent-config-stub-$$.mjs"
_CFG_OUT="/tmp/agent-config-smoke-$$.out"
_CFG_ERR="/tmp/agent-config-smoke-$$.err"
_CFG_BASE="http://127.0.0.1:$_CFG_PORT/mcp"

# .mjs, not .js: /tmp has no package.json, so a .js file there would be loaded
# as CommonJS and the `import` below would fail for reasons of its own.
cat >"$_CFG_STUB" <<'STUB'
import http from "node:http";
const TOKEN = process.env.STUB_TOKEN;
const CONFIG = { mode: "semi", enabled: true, runAt: ["09:00", "15:00"], runDays: ["mon", "wed", "fri"] };
const CREDS = {
  authType: "api_key", token: "stub-credential", model: "stub-model",
  baseUrl: "", provider: "anthropic", wire: "messages",
};
http.createServer((req, res) => {
  if (req.url === "/api/agent/config") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify(CONFIG));
    return;
  }
  if (req.url === "/api/agent/llm-credentials") {
    // Mirrors the app service: the shared secret has to arrive in the header,
    // so a 200 here also proves agent-config.js forwarded it.
    if (req.headers["x-agent-token"] !== TOKEN) { res.writeHead(403); res.end(); return; }
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify(CREDS));
    return;
  }
  res.writeHead(404); res.end();
}).listen(Number(process.env.STUB_PORT), "127.0.0.1");
STUB

STUB_TOKEN="$_CFG_TOKEN" STUB_PORT="$_CFG_PORT" \
  node "$_CFG_STUB" >/tmp/agent-config-stub-$$.log 2>&1 &
_CFG_PID=$!

# Give the stub a moment to start
sleep 1

# The `config` endpoint path.  Note FAKE_AGENT_CONFIG is deliberately NOT set:
# it short-circuits before the HTTP branch and would make this check vacuous.
TRUTHCV_MCP_URL="$_CFG_BASE" node "$AGENT_DIR/agent-config.js" mode >"$_CFG_OUT" 2>"$_CFG_ERR"
_CFG_RC=$?
if [[ $_CFG_RC -eq 0 ]] && [[ "$(cat "$_CFG_OUT")" == "semi" ]] && [[ ! -s "$_CFG_ERR" ]]; then
  ok "agent-config.js mode -> 'semi' over HTTP (config fetch path runs clean)"
else
  bad "agent-config.js mode failed: exit $_CFG_RC, stdout '$(cat "$_CFG_OUT")', stderr '$(tr '\n' ' ' <"$_CFG_ERR")'"
fi

TRUTHCV_MCP_URL="$_CFG_BASE" node "$AGENT_DIR/agent-config.js" run_at >"$_CFG_OUT" 2>"$_CFG_ERR"
_CFG_RC=$?
if [[ $_CFG_RC -eq 0 ]] && [[ "$(cat "$_CFG_OUT")" == "09:00,15:00" ]] && [[ ! -s "$_CFG_ERR" ]]; then
  ok "agent-config.js run_at -> '09:00,15:00' over HTTP"
else
  bad "agent-config.js run_at failed: exit $_CFG_RC, stdout '$(cat "$_CFG_OUT")', stderr '$(tr '\n' ' ' <"$_CFG_ERR")'"
fi

# The `llm-credentials` endpoint path - a separate branch with its own fetch.
# daily-apply.sh reads the result by line position, so the line count is part
# of the contract, not a detail.
AGENT_API_TOKEN="$_CFG_TOKEN" TRUTHCV_MCP_URL="$_CFG_BASE" \
  node "$AGENT_DIR/agent-config.js" llm_credentials >"$_CFG_OUT" 2>"$_CFG_ERR"
_CFG_RC=$?
_CFG_NL=$(wc -l <"$_CFG_OUT")
if [[ $_CFG_RC -eq 0 ]] && [[ "$_CFG_NL" -eq 6 ]] \
   && [[ "$(sed -n 1p "$_CFG_OUT")" == "api_key" ]] \
   && [[ "$(sed -n 5p "$_CFG_OUT")" == "anthropic" ]] \
   && [[ ! -s "$_CFG_ERR" ]]; then
  ok "agent-config.js llm_credentials -> 6 lines, token forwarded in X-Agent-Token"
else
  bad "agent-config.js llm_credentials failed: exit $_CFG_RC, $_CFG_NL line(s), stderr '$(tr '\n' ' ' <"$_CFG_ERR")'"
fi

# Missing shared secret must be exit 2, distinct from the exit 1 every other
# failure uses, and must print nothing on either stream.
env -u AGENT_API_TOKEN TRUTHCV_MCP_URL="$_CFG_BASE" \
  node "$AGENT_DIR/agent-config.js" llm_credentials >"$_CFG_OUT" 2>"$_CFG_ERR"
_CFG_RC=$?
if [[ $_CFG_RC -eq 2 ]] && [[ ! -s "$_CFG_OUT" ]] && [[ ! -s "$_CFG_ERR" ]]; then
  ok "agent-config.js llm_credentials without AGENT_API_TOKEN -> exit 2, silent"
else
  bad "agent-config.js llm_credentials without a token: expected silent exit 2, got exit $_CFG_RC, stdout '$(cat "$_CFG_OUT")', stderr '$(tr '\n' ' ' <"$_CFG_ERR")'"
fi

kill "$_CFG_PID" 2>/dev/null
wait "$_CFG_PID" 2>/dev/null

# With the stub gone the same port refuses connections, which is the caller
# contract's error path: nothing on stdout, nothing on stderr, exit 1.  An
# unhandled exception would satisfy the exit code and fail the stderr check.
TRUTHCV_MCP_URL="$_CFG_BASE" node "$AGENT_DIR/agent-config.js" mode >"$_CFG_OUT" 2>"$_CFG_ERR"
_CFG_RC=$?
if [[ $_CFG_RC -eq 1 ]] && [[ ! -s "$_CFG_OUT" ]] && [[ ! -s "$_CFG_ERR" ]]; then
  ok "agent-config.js unreachable app -> exit 1 with both streams silent"
else
  bad "agent-config.js unreachable app: expected silent exit 1, got exit $_CFG_RC, stdout '$(cat "$_CFG_OUT")', stderr '$(tr '\n' ' ' <"$_CFG_ERR")'"
fi

rm -f "$_CFG_STUB" "$_CFG_OUT" "$_CFG_ERR" "/tmp/agent-config-stub-$$.log"

# --- Scheduler honours the enabled toggle -------------------------------------

# The agent-level `enabled` flag lives on the Agents page and is fetched by
# supervisor.js via agent-config.js. Nothing inside the container used to read
# it: the scheduler called doRun() unconditionally, so turning the agent off
# stopped nothing. `node --check` cannot see that, and neither can a status
# probe - the only evidence that discriminates is whether a scheduled slot
# actually fires. So this runs two supervisors against the SAME slot, one
# behind a config stub saying enabled:false and one saying enabled:true, and
# insists they disagree. A pass needs both halves: the true side proves the
# slot really came round, without which the false side's silence means nothing.
_GATE_OK=1
_GATE_STUB="/tmp/agent-gate-stub-$$.mjs"

# Slot = the minute containing now+70s, so the wait below is 18-78s.
_GATE_TS=$(( $(date +%s) + 70 ))
_GATE_HHMM=$(date -d "@$_GATE_TS" +%H:%M)
_GATE_SLOT=$(date -d "$(date -d "@$_GATE_TS" +%Y-%m-%dT%H:%M:00)" +%s)

cat >"$_GATE_STUB" <<'GATESTUB'
import http from "node:http";
// runDays covers all seven days: the slot is minutes away, and the smoke test
// must not pass vacuously by landing on a day the schedule excludes.
const CONFIG = {
  mode: "semi",
  enabled: process.env.STUB_ENABLED === "true",
  runAt: [process.env.STUB_RUN_AT],
  runDays: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
};
http.createServer((req, res) => {
  if (req.url === "/api/agent/config") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify(CONFIG));
    return;
  }
  res.writeHead(404); res.end();
}).listen(Number(process.env.STUB_PORT), "127.0.0.1");
GATESTUB

# start_gate_side <enabled> <stub-port> <supervisor-port> -> echoes "stubpid superpid"
start_gate_side() {
  local want="$1" cfg_port="$2" sup_port="$3"
  STUB_ENABLED="$want" STUB_PORT="$cfg_port" STUB_RUN_AT="$_GATE_HHMM" \
    node "$_GATE_STUB" >"/tmp/agent-gate-stub-$want-$$.log" 2>&1 &
  local stub_pid=$!
  sleep 1
  AGENT_API_TOKEN="gate-token-$$" \
  AGENT_CONTROL_PORT="$sup_port" \
  AGENT_CONFIG_JS="$AGENT_DIR/agent-config.js" \
  TRUTHCV_MCP_URL="http://127.0.0.1:$cfg_port/mcp" \
  RUN_ONCE="" \
  DAILY_APPLY="/bin/true" \
    node "$AGENT_DIR/supervisor.js" >"/tmp/agent-gate-super-$want-$$.log" 2>&1 &
  echo "$stub_pid $!"
}

# gate_started <supervisor-port> -> prints "true"/"false"/"error:..."
gate_started() {
  GATE_PORT="$1" GATE_TOKEN="gate-token-$$" node -e '
    const http = require("http");
    const opts = {
      hostname: "127.0.0.1", port: Number(process.env.GATE_PORT),
      path: "/status", method: "GET",
      headers: { "x-agent-token": process.env.GATE_TOKEN },
    };
    const r = http.request(opts, (res) => {
      let b = ""; res.on("data", (c) => b += c);
      res.on("end", () => {
        if (res.statusCode !== 200) { console.log("error:HTTP " + res.statusCode); return; }
        try { console.log(String(JSON.parse(b).lastStartedAt !== null)); }
        catch { console.log("error:status not JSON"); }
      });
    });
    r.on("error", (e) => console.log("error:" + e.message));
    r.end();
  ' 2>/dev/null
}

read -r _GATE_OFF_STUB _GATE_OFF_SUP <<<"$(start_gate_side false 19096 19094)"
read -r _GATE_ON_STUB  _GATE_ON_SUP  <<<"$(start_gate_side true  19097 19095)"

# +8s past the slot: the scheduler arms a setTimeout for it, so the run starts
# within milliseconds of the slot, not on the next poll.
_GATE_WAIT=$(( _GATE_SLOT + 8 - $(date +%s) ))
[[ $_GATE_WAIT -gt 0 ]] && sleep "$_GATE_WAIT"

_GATE_OFF_RAN=$(gate_started 19094)
_GATE_ON_RAN=$(gate_started 19095)

kill "$_GATE_OFF_SUP" "$_GATE_ON_SUP" "$_GATE_OFF_STUB" "$_GATE_ON_STUB" 2>/dev/null
wait "$_GATE_OFF_SUP" "$_GATE_ON_SUP" "$_GATE_OFF_STUB" "$_GATE_ON_STUB" 2>/dev/null

if [[ "$_GATE_ON_RAN" == "true" ]]; then
  ok "scheduler fires the $_GATE_HHMM slot when the agent config says enabled:true"
else
  bad "scheduler did NOT fire the $_GATE_HHMM slot with enabled:true (got '$_GATE_ON_RAN') - the enabled:false result below proves nothing; see /tmp/agent-gate-super-true-$$.log"
  _GATE_OK=0
fi

if [[ "$_GATE_OFF_RAN" == "false" ]]; then
  [[ $_GATE_OK -eq 1 ]] \
    && ok "scheduler holds the same slot when the agent config says enabled:false" \
    || bad "enabled:false did not run, but the enabled:true control did not run either - result is not evidence"
else
  bad "scheduler ran with enabled:false (got '$_GATE_OFF_RAN') - the Agents page toggle does not stop unattended runs; see /tmp/agent-gate-super-false-$$.log"
fi

rm -f "$_GATE_STUB" "/tmp/agent-gate-stub-true-$$.log" "/tmp/agent-gate-stub-false-$$.log"

# --- Reachability ------------------------------------------------------------

# This only proves the `browser` compose service is accepting connections and
# speaking HTTP, NOT that the MCP session handshake succeeds - do NOT check
# the status code here. MCP's streamable-HTTP transport answers a bare GET
# (no session id, no `Accept: text/event-stream` header) with a 4xx - 400,
# 405 or 406 - BY DESIGN, so a healthy server will never return 200 to this
# probe. Only a connection error or a timeout means unreachable.
#
# `browser` is now the only valid AGENT_BROWSER_DRIVER value, so anything
# else must fail this probe rather than be reported as an ok skip.
if [[ "$AGENT_BROWSER_DRIVER" == "browser" ]]; then
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
else
  bad "unknown AGENT_BROWSER_DRIVER '$AGENT_BROWSER_DRIVER' - expected 'browser'"
fi

# --- mcp.json sanity ---------------------------------------------------------

if jq -e . "$AGENT_DIR/mcp.json" >/dev/null 2>&1; then
  ok "mcp.json is valid JSON"

  # daily-apply.sh's allow-list, not this file, is what grants the browser
  # server; it can only grant what is declared here.
  for srv in truthcv browser; do
    if jq -e --arg s "$srv" '.mcpServers[$s]' "$AGENT_DIR/mcp.json" >/dev/null 2>&1; then
      ok "mcp.json declares the '$srv' server"
    else
      bad "mcp.json is missing the '$srv' server entry"
    fi
  done
else
  bad "mcp.json is not valid JSON"
fi

# A bare GET here would prove nothing: the app serves an SPA catch-all, so every
# URL under it answers 200 and the old probe passed while all eleven tools failed
# to register. Do the real MCP handshake instead - initialize, initialized,
# tools/list - and insist on the eleven tools by name.
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
      "check_cooldown", "generate_cover_letter", "get_approved_applications",
      "get_canonical_cv", "get_job_profiles", "get_profile_answers",
      "recommend_salary", "record_application", "record_company_board",
      "record_screening", "report_apply_failure",
      "start_run", "finish_run", "record_run_note", "record_postings_seen",
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
