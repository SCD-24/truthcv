#!/usr/bin/env node
// agent/supervisor.js — always-on control server + scheduler for the agent
// container. Node 22, zero deps beyond Node builtins.
//
// HTTP surface (all require X-Agent-Token header matching AGENT_API_TOKEN):
//   POST /run    — trigger a run immediately; fire-and-forget
//   GET  /status — return {running, lastStartedAt, lastFinishedAt, lastExitCode}
//
// Scheduler: re-fetches schedule from agent-config.js every <=300 s, falls
// back to RUN_AT/RUN_DAYS env. Mirrors entrypoint.sh seconds_until_next_slot.
//
// RUN_ONCE=1: run once at startup then exit with the run's status.

"use strict";

const http = require("http");
const { spawnSync, spawn } = require("child_process");
const crypto = require("crypto");

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const PORT = parseInt(process.env.AGENT_CONTROL_PORT || "9099", 10);
const TOKEN = (process.env.AGENT_API_TOKEN || "").trim();
const DAILY_APPLY = process.env.DAILY_APPLY || "/app/agent/daily-apply.sh";
const AGENT_CONFIG_JS = process.env.AGENT_CONFIG_JS || "/app/agent/agent-config.js";
const RUN_AT_DEFAULT = (process.env.RUN_AT || "09:00,15:00").trim();
const RUN_DAYS_DEFAULT = (process.env.RUN_DAYS || "1,2,3,4,5").trim();

// ---------------------------------------------------------------------------
// Running state
// ---------------------------------------------------------------------------
/** @type {{ running: boolean, lastStartedAt: string|null, lastFinishedAt: string|null, lastExitCode: number|null }} */
const runState = {
  running: false,
  lastStartedAt: null,
  lastFinishedAt: null,
  lastExitCode: null,
};

// ---------------------------------------------------------------------------
// Schedule state
// ---------------------------------------------------------------------------
let scheduleRunAt = RUN_AT_DEFAULT;
let scheduleRunDays = RUN_DAYS_DEFAULT;
let scheduleRefreshedAt = 0; // epoch ms of last successful refresh

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------
function log(...args) {
  const ts = new Date()
    .toISOString()
    .replace("T", " ")
    .slice(0, 19);
  process.stdout.write(`${ts}  ${args.join(" ")}\n`);
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
/** Constant-time match of the request token against AGENT_API_TOKEN. */
function tokenOk(given) {
  if (!TOKEN) return false;
  const a = Buffer.from(given || "", "utf8");
  const b = Buffer.from(TOKEN, "utf8");
  // Always run the comparison to avoid short-circuit timing leaks.
  const len = Math.max(a.length, b.length);
  const pa = Buffer.concat([a, Buffer.alloc(Math.max(0, len - a.length))]);
  const pb = Buffer.concat([b, Buffer.alloc(Math.max(0, len - b.length))]);
  const match = crypto.timingSafeEqual(pa, pb);
  return match && a.length === b.length;
}

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------
function doRun() {
  const stamp = new Date()
    .toISOString()
    .replace("T", "_")
    .replace(/\.\d{3}Z$/, "")
    .replace(/:/g, "");

  log(`=== run ${stamp} starting ===`);
  runState.running = true;
  runState.lastStartedAt = new Date().toISOString();

  const child = spawn(DAILY_APPLY, [], {
    stdio: "inherit",
    env: { ...process.env },
  });

  child.on("close", (code) => {
    const rc = code ?? 1;
    log(`=== run ${stamp} finished rc=${rc} ===`);
    runState.running = false;
    runState.lastFinishedAt = new Date().toISOString();
    runState.lastExitCode = rc;
  });

  child.on("error", (err) => {
    log(`=== run ${stamp} spawn error: ${err.message} ===`);
    runState.running = false;
    runState.lastFinishedAt = new Date().toISOString();
    runState.lastExitCode = 1;
  });

  return child;
}

// ---------------------------------------------------------------------------
// Schedule fetching
// ---------------------------------------------------------------------------
function refreshSchedule() {
  const now = Date.now();
  if (now - scheduleRefreshedAt < 300_000) return; // within 300 s window

  function fetchField(field) {
    try {
      const r = spawnSync("node", [AGENT_CONFIG_JS, field], {
        encoding: "utf8",
        timeout: 6000,
      });
      if (r.status === 0 && r.stdout && r.stdout.trim()) {
        return r.stdout.trim();
      }
    } catch {
      // ignore
    }
    return null;
  }

  const at = fetchField("run_at");
  const days = fetchField("run_days");

  scheduleRunAt = at || RUN_AT_DEFAULT;
  scheduleRunDays = days || RUN_DAYS_DEFAULT;
  scheduleRefreshedAt = Date.now();

  const src = at ? "config" : "env";
  log(`schedule refreshed (source=${src}): RUN_AT=${scheduleRunAt} RUN_DAYS=${scheduleRunDays}`);
}

/**
 * Mirrors entrypoint.sh seconds_until_next_slot.
 * Returns seconds until the next scheduled run (>0), or -1 if none found in 8 days.
 * @param {number} nowMs - epoch milliseconds representing "now"
 */
function secondsUntilNextSlot(nowMs) {
  const nowSec = Math.floor(nowMs / 1000);
  const slots = scheduleRunAt
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const allowedDays = scheduleRunDays
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  let best = -1;

  for (let offset = 0; offset <= 8; offset++) {
    for (const t of slots) {
      const parts = t.split(":");
      if (parts.length < 2) continue;
      const hh = parseInt(parts[0], 10);
      const mm = parseInt(parts[1], 10);
      if (isNaN(hh) || isNaN(mm)) continue;

      // Compute epoch-seconds for nowDate + offset days at HH:MM local time
      const base = new Date(nowMs);
      base.setHours(0, 0, 0, 0);
      base.setDate(base.getDate() + offset);
      base.setHours(hh, mm, 0, 0);
      const targetSec = Math.floor(base.getTime() / 1000);

      if (targetSec <= nowSec) continue;

      // JS getDay(): 0=Sun, 1=Mon … 6=Sat → ISO: Mon=1 … Sun=7
      const jsDay = base.getDay();
      const isoDow = jsDay === 0 ? 7 : jsDay;
      if (!allowedDays.includes(String(isoDow))) continue;

      const delta = targetSec - nowSec;
      if (best === -1 || delta < best) best = delta;
    }
  }

  return best;
}

// ---------------------------------------------------------------------------
// Scheduler loop
// ---------------------------------------------------------------------------
function schedulerLoop() {
  refreshSchedule();

  const secs = secondsUntilNextSlot(Date.now());
  if (secs < 0) {
    log(
      `ERROR: could not compute next slot from RUN_AT=${scheduleRunAt} RUN_DAYS=${scheduleRunDays} — retrying in 300 s`,
    );
    setTimeout(schedulerLoop, 300_000).unref();
    return;
  }

  if (secs > 300) {
    // Re-fetch schedule and recompute; do not log repeatedly
    setTimeout(schedulerLoop, 300_000).unref();
    return;
  }

  const nextDate = new Date(Date.now() + secs * 1000);
  log(`next scheduled run in ${secs}s (${nextDate.toISOString().replace("T", " ").slice(0, 16)} UTC)`);

  setTimeout(() => {
    if (!runState.running) {
      log("Scheduler: triggering run");
      doRun();
    } else {
      log("Scheduler: skipping — a run is already active");
    }
    schedulerLoop();
  }, secs * 1000).unref();
}

// ---------------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------------
function jsonReply(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(data),
  });
  res.end(data);
}

const server = http.createServer((req, res) => {
  const given = req.headers["x-agent-token"] || "";
  if (!tokenOk(given)) {
    return jsonReply(res, 403, { detail: "Forbidden" });
  }

  if (req.method === "GET" && req.url === "/status") {
    return jsonReply(res, 200, { ...runState });
  }

  if (req.method === "POST" && req.url === "/run") {
    if (runState.running) {
      return jsonReply(res, 200, { started: false, running: true });
    }
    doRun();
    return jsonReply(res, 200, { started: true, running: true });
  }

  jsonReply(res, 404, { detail: "Not found" });
});

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
if (process.env.RUN_ONCE === "1") {
  // Run once at startup then exit with the run's exit code.
  log("RUN_ONCE set — running immediately then exiting");
  const child = doRun();
  child.on("close", (code) => process.exit(code ?? 1));
  child.on("error", () => process.exit(1));
} else {
  server.listen(PORT, "0.0.0.0", () => {
    log(`supervisor control server listening on port ${PORT}`);
  });
  server.on("error", (err) => {
    log(`server error: ${err.message}`);
    process.exit(1);
  });

  schedulerLoop();
}
