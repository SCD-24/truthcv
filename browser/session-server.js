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
const fs = require("fs");
const path = require("path");
const { spawn, execFileSync } = require("child_process");
const crypto = require("crypto");

const PORT = parseInt(process.env.SESSION_SERVER_PORT || "8932", 10);
const TOKEN = (process.env.AGENT_API_TOKEN || "").trim();
const PROFILE_DIR = process.env.BROWSER_PROFILE_DIR || "/browser-profile";
const AGENT_CONTROL_PORT = process.env.AGENT_CONTROL_PORT || "9099";
const GRACE_MS = parseInt(process.env.SESSION_GRACE_MS || "180000", 10);
// How long a closed session gets to exit on SIGTERM before SIGKILL. Same
// escalation shape as agent/supervisor.js's cancel-run timer (CANCEL_GRACE_MS).
const CLOSE_GRACE_MS = parseInt(process.env.SESSION_CLOSE_GRACE_MS || "10000", 10);
const TICK_MS = 5000;

function log(...args) {
  console.log(new Date().toISOString().slice(11, 19), ...args);
}

// Resolves the Chromium binary Playwright's build ships under this image,
// rather than assuming a `chromium` executable on PATH — there isn't one
// (mcr.microsoft.com/playwright ships its browsers under /ms-playwright, not
// PATH). The directory name carries a build number that moves every time
// @playwright/mcp bumps its bundled playwright-core — see the Dockerfile's
// own comment on that same drift — so this globs for it instead of hard-
// coding a version. `chromium-*` also matches nothing under
// `chromium_headless_shell-*` (underscore, not hyphen), so that build is
// naturally excluded. SESSION_CHROME_BIN remains an override.
function resolveChromeBin() {
  if (process.env.SESSION_CHROME_BIN) return process.env.SESSION_CHROME_BIN;
  const root = "/ms-playwright";
  try {
    const build = fs
      .readdirSync(root)
      .filter((name) => name.startsWith("chromium-"))
      // Numeric, not lexicographic: build numbers grow by roughly ~90/year,
      // so a 5-digit build sharing this directory with a 4-digit one is a
      // when-not-if ("chromium-9999" would sort after "chromium-10001" as
      // strings, picking the OLDER build).
      .sort((a, b) => {
        const na = parseInt(a.slice("chromium-".length), 10);
        const nb = parseInt(b.slice("chromium-".length), 10);
        return na - nb;
      })
      .pop();
    if (build) return path.join(root, build, "chrome-linux64", "chrome");
  } catch (err) {
    log(`could not list ${root}: ${err.message}`);
  }
  log(`WARNING: no chromium build found under ${root} — attended sessions will fail to launch`);
  return "chromium"; // last resort; keeps the old (broken) default as a floor
}

const CHROME_BIN = resolveChromeBin();

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
  const { supervisorIdle, profileInUse, launch, now, graceMs, closeGraceMs = CLOSE_GRACE_MS } = deps;
  // session shape: { url, proc, startedAt, evictDeadline, closing?, closeDeadline? }
  //
  // `proc` is null for the brief window between reserving the slot and the
  // launch being confirmed (see open()), and `closing`/`closeDeadline` are
  // set once close() has signalled the browser and is waiting for it to
  // actually exit. state()'s fixed response shape ({open,url,startedAt,
  // evictDeadline}) reports BOTH of those as open:true — a reservation and a
  // browser mid-close both still hold (or are about to hold) the profile, so
  // reporting open:false during either window would let a second open, or an
  // eviction, race in against a slot that is not actually free yet.
  let session = null;

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

  // Launches the browser and waits one tick for it to fail to start.
  // spawn() (and any injected `launch`) returns synchronously even when the
  // executable does not exist — the 'error' event (ENOENT, EACCES, ...)
  // arrives asynchronously. Waiting a tick turns a missing binary into a
  // refusal instead of a session that silently never opened (and, absent any
  // listener at all, an unhandled 'error' that would throw and kill the
  // whole server — see attachExitHandler for the listener kept for the rest
  // of the process's life).
  function launchAndConfirm(url) {
    return new Promise((resolve) => {
      let proc;
      try {
        proc = launch(url);
      } catch (err) {
        log(`launch threw: ${err.message}`);
        resolve({ ok: false, reason: "launch_failed" });
        return;
      }
      if (!proc || typeof proc.on !== "function") {
        // No event surface to wait on — nothing to confirm.
        resolve({ ok: true, proc });
        return;
      }
      let settled = false;
      proc.once("error", (err) => {
        if (settled) return;
        settled = true;
        log(`launch failed: ${err.message}`);
        resolve({ ok: false, reason: "launch_failed" });
      });
      setImmediate(() => {
        if (settled) return;
        settled = true;
        resolve({ ok: true, proc });
      });
    });
  }

  // Attached once a launch is confirmed. Keeps the session in step with the
  // real process for the rest of its life: a spontaneous crash (exit) clears
  // it, and a later spawn-level error (rare, but possible after a clean
  // start) is logged instead of being left to throw as an unhandled 'error'.
  // Both listeners check identity — `session.proc === proc` — because a
  // process signalled by an earlier close()/eviction can still have this
  // listener attached when its 'exit' arrives after a NEW session has
  // already opened; without the check that stale event would null out the
  // new session (see the "stale exit" test).
  function attachExitHandler(proc) {
    if (!proc || typeof proc.on !== "function") return;
    proc.on("exit", () => {
      if (session && session.proc === proc) onBrowserExit();
    });
    proc.on("error", (err) => {
      log(`browser process error: ${err.message}`);
      if (session && session.proc === proc) onBrowserExit();
    });
  }

  async function open(url) {
    if (!validUrl(url)) return { ok: false, reason: "bad_url" };
    if (session) return { ok: false, reason: "session_open", url: session.url };

    // Reserve the slot synchronously, before the first await. Without this,
    // two POSTs racing on the same tick both see session === null through
    // every check below and both launch a Chromium — the second assignment
    // would overwrite `session`, orphaning the first process: untracked,
    // unkillable by /session/close or /session/evict, holding the profile
    // forever.
    const reservation = { url, proc: null, startedAt: null, evictDeadline: null };
    session = reservation;

    // `close()`/`evict()` refuse a proc-less (reserved-but-not-launched)
    // session rather than clearing it — see close()'s own comment — so
    // nothing in the current design can replace `session` while this
    // reservation is live. This check is the difference between relying on
    // that invariant and enforcing it: getting it wrong orphans a live
    // Chromium untracked AND throws a TypeError mutating a null session
    // (which, uncaught, used to take the whole server down) — bad enough to
    // verify explicitly at every mutation point rather than trust.
    function stillReserved() {
      return session === reservation;
    }

    let idle;
    try {
      idle = await supervisorIdle();
    } catch {
      // Fail closed. daily-apply.sh already treats an unreachable config API
      // as "do not run" rather than assuming a safe state; the same rule
      // applies here, in the other direction.
      if (stillReserved()) session = null;
      return { ok: false, reason: "agent_unreachable" };
    }
    if (!stillReserved()) return { ok: false, reason: "cancelled" };
    if (!idle) {
      session = null;
      return { ok: false, reason: "agent_running" };
    }

    let busy;
    try {
      busy = await profileInUse();
    } catch (err) {
      // Fail closed here too: an unreadable process table is not evidence
      // the profile is free — it means the probe itself is broken (procps
      // missing, /proc unmounted, exec failure) — and reading it as "free"
      // would launch a second Chromium onto a profile that may already be
      // held.
      if (stillReserved()) session = null;
      log(`profile probe failed: ${err.message}`);
      return { ok: false, reason: "probe_failed" };
    }
    if (!stillReserved()) return { ok: false, reason: "cancelled" };
    if (busy) {
      session = null;
      return { ok: false, reason: "profile_busy" };
    }

    const result = await launchAndConfirm(url);
    if (!stillReserved()) {
      // The reservation is gone. Nothing is tracking whatever just happened,
      // so a successful launch here must not be left running untracked —
      // that is the exact orphan this whole check exists to prevent.
      if (result.ok && result.proc && typeof result.proc.kill === "function") {
        try {
          result.proc.kill("SIGTERM");
        } catch (err) {
          log(`kill of an abandoned launch failed: ${err.message}`);
        }
      }
      return { ok: false, reason: "cancelled" };
    }
    if (!result.ok) {
      session = null;
      return result;
    }
    session.proc = result.proc;
    session.startedAt = now().toISOString();
    attachExitHandler(result.proc);
    log(`session opened at ${url} (pid ${result.proc && result.proc.pid})`);
    return { ok: true };
  }

  function close() {
    if (!session) return { closed: false };
    if (!session.proc) {
      // Still in open()'s reservation window — nothing has launched yet to
      // signal. Clearing `session` here would let open() resume and attach
      // a just-launched Chromium to session === null: untracked, unkillable,
      // and (pre-fix) a TypeError that took the whole server down. Refuse;
      // the caller can close it once the launch actually completes.
      return { closed: false, reserving: true };
    }
    if (session.closing) {
      // Already signalled and waiting (or escalating) — a repeat close must
      // not fire a second SIGTERM/SIGKILL escalation racing the first.
      return { closed: false, closing: true };
    }

    const proc = session.proc;
    try {
      proc.kill("SIGTERM");
    } catch (err) {
      log(`kill failed: ${err.message}`);
    }

    if (typeof proc.on === "function") {
      // Wait for the 'exit' event (attachExitHandler's listener, attached at
      // launch time, clears the session when it fires) instead of trusting
      // SIGTERM was enough: a hung renderer or a beforeunload dialog can
      // survive it, and state() must not claim the profile is free while a
      // live Chromium still holds it — the agent's eviction path would read
      // {evicting:false} and start a run onto a profile that isn't free.
      session.closing = true;
      session.closeDeadline = new Date(now().getTime() + closeGraceMs).toISOString();
      log(`session close requested (pid ${proc.pid}); waiting for exit`);
      return { closed: false, closing: true };
    }

    log("session closed");
    session = null;
    return { closed: true };
  }

  function evict() {
    if (!session) return { evicting: false };
    if (!session.proc) {
      // Same reservation-window hazard as close(): stamping a deadline here
      // would let tick() call close() against a still-reserving session once
      // the grace period passed, reaching the same orphan by a longer route.
      return { evicting: false, reserving: true };
    }
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
    if (!session) return;
    if (session.closing) {
      if (session.closeDeadline && now().getTime() >= Date.parse(session.closeDeadline)) {
        log(`close escalation: still alive after grace — SIGKILL (pid ${session.proc && session.proc.pid})`);
        try {
          session.proc.kill("SIGKILL");
        } catch (err) {
          log(`SIGKILL failed: ${err.message}`);
        }
        // SIGKILL cannot be caught or blocked, so treat the profile as free
        // from here rather than waiting on an 'exit' event that (unlike a
        // plain SIGTERM) is now all but guaranteed — matching
        // agent/supervisor.js's cancel escalation, which does the same.
        session = null;
      }
      return;
    }
    if (!session.evictDeadline) return;
    if (now().getTime() >= Date.parse(session.evictDeadline)) {
      log("eviction deadline reached");
      close();
    }
  }

  function onBrowserExit() {
    if (!session) return;
    log("browser exited");
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
  //
  // Errors here are NOT read as "no chromium found": unlike the old pgrep
  // probe, `ps -eo` exits 0 whether or not anything matches, so a failure
  // means the probe itself is broken (procps missing from a rebuilt image,
  // exec failure, /proc not mounted) — not that the profile is free.
  // Propagate it so open() fails closed, the same direction as an
  // unreachable supervisor two checks earlier.
  const out = execFileSync("ps", ["-eo", "stat=,comm="], { encoding: "utf8" });
  return hasLiveChrome(out);
}

function launchBrowser(url) {
  return spawn(
    CHROME_BIN,
    [
      `--user-data-dir=${PROFILE_DIR}`,
      "--no-first-run",
      "--no-default-browser-check",
      // The container runs as root (no `user:` in compose) and Chrome
      // refuses to start as root without this — @playwright/mcp's own
      // launches in this same image already carry the equivalent flag.
      "--no-sandbox",
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
  probe_failed: 503,
  launch_failed: 500,
  cancelled: 409,
};

function createServer(manager) {
  return http.createServer(async (req, res) => {
    // Every route below runs inside this try: an async listener with no
    // catch is a single bug away from an unhandled rejection killing the
    // whole process (see the task-4 review's N1 finding — a rejection from
    // manager.open() once did exactly that), and nothing about the routes
    // added later is guaranteed to stay exception-free either.
    try {
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
    } catch (err) {
      log(`unhandled error in request handler: ${err.message}`);
      try {
        jsonReply(res, 500, { detail: "Internal error" });
      } catch {
        // Response may already be partially sent; nothing more to do.
      }
    }
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
    closeGraceMs: CLOSE_GRACE_MS,
  });
  setInterval(() => manager.tick(), TICK_MS).unref();
  const server = createServer(manager);
  server.listen(PORT, "0.0.0.0", () => log(`session server listening on port ${PORT}`));
  server.on("error", (err) => {
    log(`server error: ${err.message}`);
    process.exit(1);
  });
}
