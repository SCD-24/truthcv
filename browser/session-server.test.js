// Unit tests for the session server's decision logic, with process launching
// and the supervisor probe injected so nothing real is started.
const test = require("node:test");
const assert = require("node:assert");

const { createSessionManager, hasLiveChrome } = require("./session-server.js");

function manager(overrides = {}) {
  return createSessionManager({
    supervisorIdle: async () => true,
    profileInUse: async () => false,
    launch: () => ({ pid: 4242, kill() { this.killed = true; }, killed: false }),
    now: () => new Date("2026-08-25T12:00:00.000Z"),
    graceMs: 180000,
    ...overrides,
  });
}

test("a fresh manager reports no session", async () => {
  const m = manager();
  assert.deepStrictEqual(m.state(), {
    open: false, url: null, startedAt: null, evictDeadline: null,
  });
});

test("opening a session records its url", async () => {
  const m = manager();
  const result = await m.open("https://example.com/login");
  assert.strictEqual(result.ok, true);
  assert.strictEqual(m.state().open, true);
  assert.strictEqual(m.state().url, "https://example.com/login");
});

test("a second open is refused and names the session already running", async () => {
  const m = manager();
  await m.open("https://example.com/login");
  const result = await m.open("https://other.com/login");
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.reason, "session_open");
  assert.strictEqual(result.url, "https://example.com/login");
});

test("a running agent refuses the session", async () => {
  const m = manager({ supervisorIdle: async () => false });
  const result = await m.open("https://example.com/login");
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.reason, "agent_running");
});

test("an unreachable supervisor refuses the session (fails closed)", async () => {
  const m = manager({ supervisorIdle: async () => { throw new Error("ECONNREFUSED"); } });
  const result = await m.open("https://example.com/login");
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.reason, "agent_unreachable");
});

test("a profile already held by another chromium refuses the session", async () => {
  const m = manager({ profileInUse: async () => true });
  const result = await m.open("https://example.com/login");
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.reason, "profile_busy");
});

test("only http and https urls are accepted", async () => {
  const m = manager();
  for (const bad of ["file:///etc/passwd", "javascript:alert(1)", "not a url", ""]) {
    const result = await m.open(bad);
    assert.strictEqual(result.ok, false, `expected ${bad} to be refused`);
    assert.strictEqual(result.reason, "bad_url");
  }
});

test("closing kills the browser and clears the session", async () => {
  const proc = { pid: 1, kill() { this.killed = true; }, killed: false };
  const m = manager({ launch: () => proc });
  await m.open("https://example.com/login");
  m.close();
  assert.strictEqual(proc.killed, true);
  assert.strictEqual(m.state().open, false);
});

test("evicting sets a deadline without killing immediately", async () => {
  const m = manager();
  await m.open("https://example.com/login");
  const result = m.evict();
  assert.strictEqual(result.evicting, true);
  assert.strictEqual(m.state().evictDeadline, "2026-08-25T12:03:00.000Z");
  assert.strictEqual(m.state().open, true);
});

test("evicting with no session open is a no-op, not an error", async () => {
  const m = manager();
  const result = m.evict();
  assert.strictEqual(result.evicting, false);
});

test("a second evict does not extend the first deadline", async () => {
  let t = new Date("2026-08-25T12:00:00.000Z");
  const m = manager({ now: () => t });
  await m.open("https://example.com/login");
  m.evict();
  t = new Date("2026-08-25T12:01:00.000Z");
  m.evict();
  assert.strictEqual(m.state().evictDeadline, "2026-08-25T12:03:00.000Z");
});

test("the deadline passing closes the session", async () => {
  let t = new Date("2026-08-25T12:00:00.000Z");
  const proc = { pid: 1, kill() { this.killed = true; }, killed: false };
  const m = manager({ now: () => t, launch: () => proc });
  await m.open("https://example.com/login");
  m.evict();
  t = new Date("2026-08-25T12:03:01.000Z");
  m.tick();
  assert.strictEqual(proc.killed, true);
  assert.strictEqual(m.state().open, false);
});

test("a browser that exits on its own clears the session", async () => {
  const m = manager();
  await m.open("https://example.com/login");
  m.onBrowserExit();
  assert.strictEqual(m.state().open, false);
});

// hasLiveChrome parses `ps -eo stat=,comm=` output directly, so these run
// against representative ps output rather than a spawned process.
test("hasLiveChrome ignores zombie-only chromium output", () => {
  const ps = "Z  chrome\nZ  chrome_crashpad\n";
  assert.strictEqual(hasLiveChrome(ps), false);
});

test("hasLiveChrome detects a live chromium", () => {
  const ps = "S  chrome\n";
  assert.strictEqual(hasLiveChrome(ps), true);
});

test("hasLiveChrome detects a live chromium mixed with zombies", () => {
  const ps = "Z  chrome\nS  chrome\nZ  chrome_crashpad\n";
  assert.strictEqual(hasLiveChrome(ps), true);
});

test("hasLiveChrome is false when no chrome process is present", () => {
  const ps = "S  node\nS  Xvfb\n";
  assert.strictEqual(hasLiveChrome(ps), false);
});
