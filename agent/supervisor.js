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
import https from "node:https";
import fs from "node:fs";
import path from "node:path";
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
const RUN_LOG_DIR = process.env.RUN_LOG_DIR || "/app/runs";
// The app's MCP base URL; the run-accounting routes hang off the same origin
// with the /mcp suffix stripped, exactly as agent-config.js derives
// /api/agent/config and /api/agent/llm-credentials from it.
const TRUTHCV_MCP_URL = process.env.TRUTHCV_MCP_URL || "";

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

// The agent-level enabled toggle from the Agents page. Three-valued on
// purpose: null means "never successfully fetched", which is NOT the same as
// false and must not be logged as if the operator had turned the agent off.
// Only `true` lets the scheduler fire — see schedulerLoop. Unlike RUN_AT and
// RUN_DAYS there is no env fallback, because there is no env answer to "did
// the operator switch this off"; the app is the only source.
let scheduleEnabled = null;

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
// Run accounting
// ---------------------------------------------------------------------------
// The durable run record lives in the app (runs/store.py, on the app's data
// volume, which this container deliberately cannot mount — see the volumes
// note in docker-compose.yml). Until these calls existed, the record was only
// ever created by the model calling the `start_run` MCP tool, so a run that
// died before its first turn left nothing at all in Recent runs: a provider
// error, an aborted precondition and a container that never started were
// indistinguishable from a run that had not been triggered.
//
// Every call here is best-effort. Accounting must never fail a run, change its
// exit code, or delay it: failures are logged and dropped.

/** POST `body` as JSON to an app path, resolving to true on 2xx. Never rejects. */
function postToApp(path_, body) {
  return new Promise((resolve) => {
    if (!TRUTHCV_MCP_URL || !TOKEN) return resolve(false);
    let u;
    try {
      u = new URL(TRUTHCV_MCP_URL.replace(/\/mcp\/?$/, "") + path_);
    } catch {
      return resolve(false);
    }
    const payload = JSON.stringify(body);
    const mod = u.protocol === "https:" ? https : http;
    const req = mod.request(
      u,
      {
        method: "POST",
        timeout: 5000,
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(payload),
          "X-Agent-Token": TOKEN,
        },
      },
      (res) => {
        res.resume();
        res.on("end", () => resolve(res.statusCode >= 200 && res.statusCode < 300));
      },
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
    req.end(payload);
  });
}

/**
 * The reason file daily-apply.sh leaves behind when it aborts on a
 * precondition or skips because the agent is switched off.
 *
 * The exit code alone cannot say *which* precondition failed — every abort()
 * in that script exits 1 — and the run log naming it is a file the operator
 * has to go and find. Reading it here puts the actual sentence on the run
 * record. Consumed (unlinked) on read so it can never be attributed to a
 * later run.
 */
function takeReasonFile(runId) {
  const file = path.join(RUN_LOG_DIR, `${runId}.reason`);
  try {
    const text = fs.readFileSync(file, "utf8").trim();
    fs.unlinkSync(file);
    return text;
  } catch {
    return "";
  }
}

/**
 * Map a daily-apply.sh exit code to a run status and an operator-readable
 * reason.
 *
 * The harness's codes are its machine contract, documented at its invocation
 * in daily-apply.sh and produced by exitCodeFor() in agent/harness/cli.ts:
 * 0 success, 2 turn cap, 3 provider error, 4 MCP connection failure, 5 bad
 * configuration. 1 is daily-apply.sh's own abort(); 143/137 are the signalled
 * exits a cancel produces.
 */
function outcomeFor(rc, cancelled, reason) {
  if (cancelled || rc === 143 || rc === 137) {
    return { status: "cancelled", stoppedReason: reason || "cancelled by the operator" };
  }
  if (rc === 0) return { status: "completed", stoppedReason: reason };
  const known = {
    1: "run aborted before the agent started — see the run log",
    2: "stopped at the harness turn cap (AGENT_MAX_TURNS)",
    3: "the LLM provider rejected every attempt — see the run log for the provider's error",
    4: "could not connect to an MCP server (the app's tools, or the browser)",
    5: "the harness was misconfigured — see the run log",
  };
  return {
    status: "failed",
    stoppedReason: reason || known[rc] || `the run exited with code ${rc}`,
  };
}

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------
/**
 * Start a run.
 *
 * @param {string} trigger - what started it ("scheduled", "manual" or
 *   "startup"), recorded on the run record. The model's own start_run tool
 *   could only ever guess this, so it always said "scheduled".
 * @param {(rc: number) => void} [onSettled] - called once the run has exited
 *   AND its record has been closed out. RUN_ONCE exits the process from here
 *   rather than from the child's close event, so the finish call is not cut
 *   off mid-flight.
 */
function doRun(trigger = "manual", onSettled) {
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

  // Create the run record before the child does anything, so a run that dies
  // in its preconditions or on its very first model call is still accounted
  // for. The child's own start_run lands on this same id and joins it
  // (runs.store.start is idempotent).
  //
  // Kept as a promise rather than awaited: doRun must return the child
  // synchronously for /run and RUN_ONCE. settle() awaits it before closing the
  // record, so a child that dies instantly cannot have its finish overtake its
  // start and leave a record stuck at "running".
  const started = postToApp(`/api/agent/runs/${runId}/start`, { trigger });

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
    const cancelled = runState.cancelling;
    currentChild = null;
    runState.running = false;
    runState.lastCancelled = cancelled;
    runState.cancelling = false;
    runState.lastFinishedAt = new Date().toISOString();
    runState.lastExitCode = rc;
    // lastRunId is retained so a client can still correlate this finished run
    // with its durable record; only currentRunId (the "a run is active" flag)
    // is cleared.
    runState.currentRunId = null;

    // Close the record out. This is the ONLY path that sees every ending: a
    // run SIGKILLed after a cancel, or one whose shell never started, runs no
    // in-container code of its own. finish_if_running leaves a record the
    // model already closed with its own finish_run alone — that account names
    // where the run actually stopped and is the better one.
    const outcome = outcomeFor(rc, cancelled, takeReasonFile(runId));
    started
      .then(() => postToApp(`/api/agent/runs/${runId}/finish`, outcome))
      .then((ok) => {
        if (!ok) log(`run ${runId}: could not record the run outcome with the app`);
      })
      .finally(() => onSettled?.(rc));
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
  const enabled = fetchField("enabled");

  scheduleRunAt = at || RUN_AT_DEFAULT;
  scheduleRunDays = days || RUN_DAYS_DEFAULT;
  // Keep the last known value when the fetch fails rather than flipping to
  // false: one flaky request should not read as "the operator disabled it".
  // A run needs the app anyway (daily-apply.sh aborts without its job config),
  // so a persistently unreachable app leaves this null and the scheduler holds.
  if (enabled === "true" || enabled === "false") scheduleEnabled = enabled === "true";
  scheduleRefreshedAt = Date.now();

  const src = at ? "config" : "env";
  log(
    `schedule refreshed (source=${src}): RUN_AT=${scheduleRunAt} RUN_DAYS=${scheduleRunDays} ` +
      `enabled=${scheduleEnabled === null ? "unknown" : scheduleEnabled}`,
  );
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
    if (runState.running) {
      log("Scheduler: skipping — a run is already active");
    } else if (scheduleEnabled === false) {
      log("Scheduler: skipping — the agent is disabled on the Agents page");
    } else if (scheduleEnabled === null) {
      log("Scheduler: skipping — enabled flag unknown (agent config fetch failed)");
    } else {
      log("Scheduler: triggering run");
      doRun("scheduled");
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
    // scheduleEnabled is the scheduler's gate, reported so an operator (and
    // agent/smoke-test.sh) can see which way it is set without reading logs.
    return jsonReply(res, 200, { ...runState, scheduleEnabled });
  }

  if (req.method === "POST" && req.url === "/run") {
    // Deliberately NOT gated on scheduleEnabled. This route is only reached
    // from the Agents page's Run-now button — an explicit operator action, in
    // front of them, now. The toggle governs unattended runs, which is the
    // thing nobody is watching.
    if (runState.running) {
      return jsonReply(res, 200, { started: false, running: true });
    }
    doRun("manual");
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
  // Exit from onSettled, not from the child's own close event: settle() has an
  // in-flight HTTP call closing the run record out, and exiting on `close`
  // would kill the process before it lands, leaving the record at "running"
  // forever. onSettled fires after that call has finished (or failed).
  doRun("startup", (rc) => process.exit(rc));
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
