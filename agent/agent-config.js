// Fetch one field of the agent config from the app service. The agent image
// has no curl (see daily-apply.sh's note); node is the only HTTP client.
// Usage: node agent-config.js mode|enabled|run_at|run_days|llm_credentials
// Errors print nothing and exit 1 — callers fall back to env defaults.
import nodeHttp from "node:http";
import nodeHttps from "node:https";

const field = process.argv[2];
const DAY_NUM = { mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6, sun: 7 };
// Stand-in/test hook: FAKE_AGENT_CONFIG, when set, is served as the config
// payload without any HTTP call (used by out-of-container harnesses).
if (process.env.FAKE_AGENT_CONFIG && field !== "llm_credentials") {
  const cfg = JSON.parse(process.env.FAKE_AGENT_CONFIG);
  if (field === "job_config") {
    process.stdout.write(
      JSON.stringify({
        profiles: cfg.profiles || [],
        targetCompanies: cfg.targetCompanies || [],
        cooldownDays: cfg.cooldownDays,
        cooldownDaysSameRole: cfg.cooldownDaysSameRole,
        cooldownDaysSameCompany: cfg.cooldownDaysSameCompany,
        maxApplicationsPerRun: cfg.maxApplicationsPerRun,
        maxPostingAgeDays: cfg.maxPostingAgeDays,
        companyBoards: cfg.companyBoards || [],
        searchQueries: cfg.searchQueries || [],
      })
    );
    process.exit(0);
  }
  if (field === "mode") {
    if (typeof cfg.mode !== "string") process.exit(1);
    process.stdout.write(cfg.mode);
    process.exit(0);
  }
}
const base = process.env.TRUTHCV_MCP_URL;
if (!base || !["enabled", "mode", "run_at", "run_days", "llm_credentials", "job_config"].includes(field)) process.exit(1);

if (field === "llm_credentials") {
  // Distinct exit code (2) when the shared secret itself is missing, so
  // daily-apply.sh can tell "not configured" apart from "fetch failed" if it
  // ever needs to. The token is read from the env and forwarded in a header;
  // it is never written anywhere else (not logged, not echoed).
  const token = process.env.AGENT_API_TOKEN;
  if (!token) process.exit(2);
  let cu;
  try { cu = new URL(base.replace(/\/mcp\/?$/, "") + "/api/agent/llm-credentials"); }
  catch { process.exit(1); }
  const chttp = cu.protocol === "https:" ? nodeHttps : nodeHttp;
  const creq = chttp.get(cu, { timeout: 5000, headers: { "X-Agent-Token": token } }, (res) => {
    if (res.statusCode !== 200) { res.resume(); process.exit(1); }
    let body = "";
    res.on("data", (c) => (body += c));
    res.on("end", () => {
      try {
        const creds = JSON.parse(body);
        // Line 4 is the Anthropic-compatible base URL, empty for Anthropic
        // itself. Appended last so an older daily-apply.sh reading only
        // three lines is unaffected. Lines 5 (provider) and 6 (wire) are the
        // newest additions, appended after baseUrl for the same reason: a
        // reader that only wants the earlier lines keeps working, and an
        // older API server that omits provider/wire degrades to empty lines
        // (via `|| ""`) rather than crashing, so output stays exactly 6 lines.
        process.stdout.write(`${creds.authType}\n${creds.token}\n${creds.model || ""}\n${creds.baseUrl || ""}\n${creds.provider || ""}\n${creds.wire || ""}\n`);
        process.exit(0);
      } catch { process.exit(1); }
    });
  });
  creq.on("error", () => process.exit(1));
  creq.on("timeout", () => { creq.destroy(); process.exit(1); });
} else {
let u;
try { u = new URL(base.replace(/\/mcp\/?$/, "") + "/api/agent/config"); } catch { process.exit(1); }
const http = u.protocol === "https:" ? nodeHttps : nodeHttp;
const req = http.get(u, { timeout: 5000 }, (res) => {
  if (res.statusCode !== 200) { res.resume(); process.exit(1); }
  let body = "";
  res.on("data", (c) => (body += c));
  res.on("end", () => {
    try {
      const cfg = JSON.parse(body);
      if (field === "mode") {
        if (typeof cfg.mode !== "string") { process.exit(1); return; }
        process.stdout.write(cfg.mode);
      }
      else if (field === "enabled") {
        if (typeof cfg.enabled !== "boolean") { process.exit(1); return; }
        process.stdout.write(String(cfg.enabled));
      }
      else if (field === "run_at") process.stdout.write(cfg.runAt.join(","));
      else if (field === "run_days") process.stdout.write(cfg.runDays.map((d) => DAY_NUM[d]).filter(Boolean).join(","));
      else if (field === "job_config") {
        const payload = {
          profiles: cfg.profiles || [],
          targetCompanies: cfg.targetCompanies || [],
          cooldownDays: cfg.cooldownDays,
          // Per-window cooldown overrides; undefined stays absent so the
          // shell side's `// "not configured"` fallbacks keep working.
          cooldownDaysSameRole: cfg.cooldownDaysSameRole,
          cooldownDaysSameCompany: cfg.cooldownDaysSameCompany,
          maxApplicationsPerRun: cfg.maxApplicationsPerRun,
          maxPostingAgeDays: cfg.maxPostingAgeDays,
          companyBoards: cfg.companyBoards || [],
          searchQueries: cfg.searchQueries || [],
        };
        process.stdout.write(JSON.stringify(payload));
      }
      process.exit(0);
    } catch { process.exit(1); }
  });
});
req.on("error", () => process.exit(1));
req.on("timeout", () => { req.destroy(); process.exit(1); });
}
