#!/usr/bin/env node
// agent/supervisor.js — always-on control server + scheduler for the agent
// container. Node 22, zero deps beyond Node builtins.
//
// HTTP surface (all require X-Agent-Token header matching AGENT_API_TOKEN):
//   POST /run    — trigger a run immediately; fire-and-forget
//   POST /cancel — stop the run in progress; fire-and-forget
//   GET  /status — return {running, cancelling, lastStartedAt, lastFinishedAt,
//                          lastExitCode, lastCancelled}
//
// Scheduler: re-fetches schedule from agent-config.js every <=300 s, falls
// back to RUN_AT/RUN_DAYS env. Mirrors entrypoint.sh seconds_until_next_slot.
//
// RUN_ONCE=1: run once at startup then exit with the run's status.

import http from "node:http";
import { spawnSync, spawn } from "node:child_process";
import crypto from "node:crypto";

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
/** @type {{ running: boolean, cancelling: boolean, lastStartedAt: string|null, lastFinishedAt: string|null, lastExitCode: number|null, lastCancelled: boolean, currentRunId: string|null, lastRunId: string|null }} */
const runState = {
  running: false,
  cancelling: false,
  lastStartedAt: null,
  lastFinishedAt: null,
  lastExitCode: null,
  lastCancelled: false,
  // The run id of the run in progress, threaded to the child via
  // TRUTHCV_RUN_ID so it can call start_run/finish_run with it. Durable
  // accounting for the run lives in the run store (runs/store.py), reached
  // over the API — this is in-memory only, for the status route.
  currentRunId: null,
  // The run id of the most recently started run, kept after it ends so a
  // client can still correlate the last completed run with its record.
  lastRunId: null,
};

// Shell convention for a signalled process: 128 + signal number. Node gives the
// name, not the number, and only the two this supervisor ever sends can appear
// here — anything else falls back to 1 rather than inventing a code.
const SIGNAL_EXIT_CODES = { SIGTERM: 143, SIGKILL: 137 };

/** Exit code for a child that died on `signal`, or 1 when it did not. */
function signalExitCode(signal) {
  return signal ? (SIGNAL_EXIT_CODES[signal] ?? 1) : 1;
}

/** The daily-apply child of the run in progress, or null when idle. */
let currentChild = null;

/** SIGKILL escalation timer for a cancel in progress, so it can be cleared. */
let killTimer = null;

// How long a cancelled run gets to exit on SIGTERM before SIGKILL. daily-apply.sh
// and the Node harness process it spawns have MCP servers and a headful browser
// session to tear down, so this is generous; the escalation exists for a wedged
// run, not a slow one.
const CANCEL_GRACE_MS = parseInt(process.env.AGENT_CANCEL_GRACE_MS || "10000", 10);

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

  const runId = crypto.randomUUID();

  log(`=== run ${stamp} starting (run_id=${runId}) ===`);
  runState.running = true;
  runState.cancelling = false;
  runState.lastCancelled = false;
  runState.lastStartedAt = new Date().toISOString();
  runState.currentRunId = runId;
  runState.lastRunId = runId;

  // detached: the run is a tree — daily-apply.sh, the Node harness process it
  // spawns, and the stdio MCP servers under it. Its own process group is what
  // lets cancel reach all of them with one signal; signalling the shell alone
  // would orphan the harness.
  //
  // The headful browser is NOT in this tree: Chromium runs in the sibling
  // `browser` container, reached over HTTP MCP, in another PID namespace. A
  // cancel therefore drops the MCP session without closing it, and that
  // container's page state survives until it restarts.
  const child = spawn(DAILY_APPLY, [], {
    stdio: "inherit",
    env: { ...process.env, TRUTHCV_RUN_ID: runId },
    detached: true,
  });
  currentChild = child;

  /** Common teardown for both exit paths: never leave state mid-cancel. */
  function settle(rc) {
    if (killTimer !== null) {
      clearTimeout(killTimer);
      killTimer = null;
    }
    currentChild = null;
    runState.running = false;
    runState.lastCancelled = runState.cancelling;
    runState.cancelling = false;
    runState.lastFinishedAt = new Date().toISOString();
    runState.lastExitCode = rc;
    // lastRunId is retained so a client can still correlate this finished run
    // with its durable record; only currentRunId (the "a run is active" flag)
    // is cleared.
    runState.currentRunId = null;
  }

  child.on("close", (code, signal) => {
    const rc = code ?? signalExitCode(signal);
    const how = runState.cancelling ? "cancelled" : "finished";
    log(`=== run ${stamp} ${how} rc=${rc}${signal ? ` signal=${signal}` : ""} ===`);
    settle(rc);
  });

  child.on("error", (err) => {
    log(`=== run ${stamp} spawn error: ${err.message} ===`);
    settle(1);
  });

  return child;
}

/**
 * Stop the run in progress by signalling its whole process group.
 *
 * Returns false when nothing is running or a cancel is already under way, so
 * a double click on the operator's Cancel button is a no-op rather than a
 * second SIGKILL escalation racing the first.
 */
function cancelRun() {
  // `cancelling` alone was a one-shot latch: if the group survived the SIGKILL
  // escalation, a second cancel was refused forever, the button stayed on
  // "Stopping…", and only a container restart recovered. Refuse only while an
  // escalation is still pending; once it has fired, a repeat cancel may retry.
  const escalationPending = runState.cancelling && killTimer !== null;
  if (!runState.running || currentChild === null || escalationPending) {
    return false;
  }
  const pid = currentChild.pid;
  log(`cancel requested — SIGTERM to process group ${pid}`);
  try {
    process.kill(-pid, "SIGTERM");
    // Only now: a run that had already exited was never cancelled by us, and
    // reporting it as cancelled hid its real exit code behind "Last run
    // cancelled" in the UI.
    runState.cancelling = true;
  } catch (err) {
    // ESRCH here means the run exited between the status check and the signal
    // — or, far less likely, that the pid was recycled. Either way nothing of
    // ours was signalled, so this is not a cancellation.
    log(`cancel: SIGTERM not delivered (${err.code || err.message}) — run was already exiting`);
    return false;
  }

  killTimer = setTimeout(() => {
    killTimer = null;
    // Signal the pid captured when the cancel was requested, and only while
    // that is still the live run. `settle` clears this timer on every exit
    // path, so this cannot normally fire against a later run — but reading
    // `currentChild.pid` at fire time made that invariant the only thing
    // standing between a cancel and SIGKILLing a healthy successor.
    if (!runState.running || currentChild === null || currentChild.pid !== pid) return;
    log(`cancel: still running after ${CANCEL_GRACE_MS}ms — SIGKILL to group ${pid}`);
    try {
      process.kill(-pid, "SIGKILL");
    } catch (err) {
      log(`cancel: SIGKILL failed (${err.code || err.message})`);
    }
  }, CANCEL_GRACE_MS);
  killTimer.unref();

  return true;
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

  if (req.method === "POST" && req.url === "/cancel") {
    const cancelled = cancelRun();
    return jsonReply(res, 200, { cancelled, running: runState.running });
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
  child.on("close", (code, signal) => process.exit(code ?? signalExitCode(signal)));
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
