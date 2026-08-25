#!/usr/bin/env node
// Attended browser session control server.
//
// Owns ONE attended Chromium session on the persistent profile, so the
// operator can sign in to a site by hand at a time of their choosing. Mirrors
// agent/supervisor.js: same token header, same jsonReply idiom, plain node
// http with no framework.
//
// The agent's own browser is driven by @playwright/mcp in this same container
// and launches Chromium lazily per run. Only one process may hold
// /browser-profile at a time, so this server refuses to open a session while a
// run is in progress, and daily-apply.sh evicts an open session before a run
// starts. Both halves are required: either alone leaves a race.

const http = require("http");
const { spawn, execFileSync } = require("child_process");
const crypto = require("crypto");

const PORT = parseInt(process.env.SESSION_SERVER_PORT || "8932", 10);
const TOKEN = (process.env.AGENT_API_TOKEN || "").trim();
const PROFILE_DIR = process.env.BROWSER_PROFILE_DIR || "/browser-profile";
const AGENT_CONTROL_PORT = process.env.AGENT_CONTROL_PORT || "9099";
const GRACE_MS = parseInt(process.env.SESSION_GRACE_MS || "180000", 10);
const CHROME_BIN = process.env.SESSION_CHROME_BIN || "chromium";
const TICK_MS = 5000;

function log(...args) {
  console.log(new Date().toISOString().slice(11, 19), ...args);
}

// ---------------------------------------------------------------------------
// Auth — identical rule to agent/supervisor.js: no token configured means no
// request is ever accepted.
// ---------------------------------------------------------------------------
function tokenOk(given) {
  if (!TOKEN) return false;
  const a = Buffer.from(given || "", "utf8");
  const b = Buffer.from(TOKEN, "utf8");
  const len = Math.max(a.length, b.length);
  const pa = Buffer.concat([a, Buffer.alloc(Math.max(0, len - a.length))]);
  const pb = Buffer.concat([b, Buffer.alloc(Math.max(0, len - b.length))]);
  return crypto.timingSafeEqual(pa, pb) && a.length === b.length;
}

// ---------------------------------------------------------------------------
// Session manager — pure decision logic, with every side effect injected so it
// can be tested without launching a browser or reaching the agent.
// ---------------------------------------------------------------------------
function createSessionManager(deps) {
  const { supervisorIdle, profileInUse, launch, now, graceMs } = deps;
  let session = null; // { url, proc, startedAt, evictDeadline }

  function state() {
    return {
      open: session !== null,
      url: session ? session.url : null,
      startedAt: session ? session.startedAt : null,
      evictDeadline: session ? session.evictDeadline : null,
    };
  }

  function validUrl(url) {
    let parsed;
    try {
      parsed = new URL(url);
    } catch {
      return false;
    }
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  }

  async function open(url) {
    if (!validUrl(url)) return { ok: false, reason: "bad_url" };
    if (session) return { ok: false, reason: "session_open", url: session.url };

    let idle;
    try {
      idle = await supervisorIdle();
    } catch {
      // Fail closed. daily-apply.sh already treats an unreachable config API
      // as "do not run" rather than assuming a safe state; the same rule
      // applies here, in the other direction.
      return { ok: false, reason: "agent_unreachable" };
    }
    if (!idle) return { ok: false, reason: "agent_running" };

    if (await profileInUse()) return { ok: false, reason: "profile_busy" };

    const proc = launch(url);
    session = { url, proc, startedAt: now().toISOString(), evictDeadline: null };
    if (proc && typeof proc.on === "function") {
      proc.on("exit", () => onBrowserExit());
    }
    log(`session opened at ${url} (pid ${proc && proc.pid})`);
    return { ok: true };
  }

  function close() {
    if (!session) return { closed: false };
    try {
      session.proc.kill("SIGTERM");
    } catch (err) {
      log(`kill failed: ${err.message}`);
    }
    log("session closed");
    session = null;
    return { closed: true };
  }

  function evict() {
    if (!session) return { evicting: false };
    // Never extend an existing deadline: a run that asks twice must not push
    // the browser further out of its own reach.
    if (session.evictDeadline) {
      return { evicting: true, deadline: session.evictDeadline };
    }
    session.evictDeadline = new Date(now().getTime() + graceMs).toISOString();
    log(`session eviction scheduled for ${session.evictDeadline}`);
    return { evicting: true, deadline: session.evictDeadline };
  }

  function tick() {
    if (!session || !session.evictDeadline) return;
    if (now().getTime() >= Date.parse(session.evictDeadline)) {
      log("eviction deadline reached");
      close();
    }
  }

  function onBrowserExit() {
    if (!session) return;
    log("browser exited on its own");
    session = null;
  }

  return { state, open, close, evict, tick, onBrowserExit };
}

// ---------------------------------------------------------------------------
// Real side effects
// ---------------------------------------------------------------------------
function supervisorIdle() {
  return new Promise((resolve, reject) => {
    const req = http.get(
      `http://agent:${AGENT_CONTROL_PORT}/status`,
      { timeout: 5000, headers: { "X-Agent-Token": TOKEN } },
      (res) => {
        let body = "";
        res.on("data", (c) => (body += c));
        res.on("end", () => {
          try {
            const parsed = JSON.parse(body);
            resolve(parsed.running !== true);
          } catch (err) {
            reject(err);
          }
        });
      }
    );
    req.on("timeout", () => { req.destroy(); reject(new Error("timeout")); });
    req.on("error", reject);
  });
}

// Parses `ps -eo stat=,comm=` output and reports whether any LIVE chromium
// process is present. Zombies must not count: chromium exits when a run ends
// but is never reaped — browser/entrypoint.sh is PID 1 and is a bash script,
// so orphaned children accumulate as defunct entries for the life of the
// container. Counting them (as a plain `pgrep -c chrome` does) would refuse
// every attended session after the first run of the day. Exported so the
// parsing logic is testable without spawning a real `ps`.
function hasLiveChrome(psOutput) {
  return psOutput.split("\n").some((line) => {
    const [stat, comm] = line.trim().split(/\s+/);
    return stat && comm && !stat.startsWith("Z") && comm.includes("chrome");
  });
}

async function profileInUse() {
  // Any LIVE chromium process in this container means the profile may be
  // held. Cheaper and safer than interpreting SingletonLock a second time —
  // browser/entrypoint.sh already adjudicates that on startup.
  try {
    const out = execFileSync("ps", ["-eo", "stat=,comm="], { encoding: "utf8" });
    return hasLiveChrome(out);
  } catch {
    return false;
  }
}

function launchBrowser(url) {
  return spawn(
    CHROME_BIN,
    [
      `--user-data-dir=${PROFILE_DIR}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--start-maximized",
      url,
    ],
    { env: { ...process.env, DISPLAY: process.env.DISPLAY || ":99" }, stdio: "ignore" }
  );
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

function readJson(req) {
  return new Promise((resolve) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      try {
        resolve(JSON.parse(body || "{}"));
      } catch {
        resolve({});
      }
    });
  });
}

const REFUSAL_STATUS = {
  bad_url: 400,
  session_open: 409,
  agent_running: 409,
  agent_unreachable: 503,
  profile_busy: 409,
};

function createServer(manager) {
  return http.createServer(async (req, res) => {
    if (!tokenOk(req.headers["x-agent-token"] || "")) {
      return jsonReply(res, 403, { detail: "Forbidden" });
    }
    if (req.method === "GET" && req.url === "/session") {
      return jsonReply(res, 200, manager.state());
    }
    if (req.method === "POST" && req.url === "/session") {
      const body = await readJson(req);
      const result = await manager.open(body.url);
      if (!result.ok) {
        return jsonReply(res, REFUSAL_STATUS[result.reason] || 409, result);
      }
      return jsonReply(res, 200, { ...result, ...manager.state() });
    }
    if (req.method === "POST" && req.url === "/session/close") {
      return jsonReply(res, 200, manager.close());
    }
    if (req.method === "POST" && req.url === "/session/evict") {
      return jsonReply(res, 200, manager.evict());
    }
    jsonReply(res, 404, { detail: "Not found" });
  });
}

module.exports = { createSessionManager, createServer, tokenOk, hasLiveChrome };

if (require.main === module) {
  const manager = createSessionManager({
    supervisorIdle,
    profileInUse,
    launch: launchBrowser,
    now: () => new Date(),
    graceMs: GRACE_MS,
  });
  setInterval(() => manager.tick(), TICK_MS).unref();
  const server = createServer(manager);
  server.listen(PORT, "0.0.0.0", () => log(`session server listening on port ${PORT}`));
  server.on("error", (err) => {
    log(`server error: ${err.message}`);
    process.exit(1);
  });
}
