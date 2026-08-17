// Fetch one field of the agent config from the app service. The agent image
// has no curl (see daily-apply.sh's note); node is the only HTTP client.
// Usage: node agent-config.js enabled|run_at|run_days
// Errors print nothing and exit 1 — callers fall back to env defaults.
const field = process.argv[2];
const DAY_NUM = { mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6, sun: 7 };
const base = process.env.TRUTHCV_MCP_URL;
if (!base || !["enabled", "run_at", "run_days"].includes(field)) process.exit(1);
let u;
try { u = new URL(base.replace(/\/mcp\/?$/, "") + "/api/agent/config"); } catch { process.exit(1); }
const http = require(u.protocol === "https:" ? "https" : "http");
const req = http.get(u, { timeout: 5000 }, (res) => {
  if (res.statusCode !== 200) { res.resume(); process.exit(1); }
  let body = "";
  res.on("data", (c) => (body += c));
  res.on("end", () => {
    try {
      const cfg = JSON.parse(body);
      if (field === "enabled") process.stdout.write(String(cfg.enabled === true));
      else if (field === "run_at") process.stdout.write(cfg.runAt.join(","));
      else process.stdout.write(cfg.runDays.map((d) => DAY_NUM[d]).filter(Boolean).join(","));
      process.exit(0);
    } catch { process.exit(1); }
  });
});
req.on("error", () => process.exit(1));
req.on("timeout", () => { req.destroy(); process.exit(1); });
