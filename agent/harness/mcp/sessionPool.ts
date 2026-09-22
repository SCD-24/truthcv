/**
 * A pool of EXTRA MCP sessions to the `browser` server, letting
 * harvestSessions.ts's session-per-worker harvest path give each worker its
 * own browser session instead of serialising every board through the
 * harness's single shared `browser` connection (agent/harness/loop.ts's
 * `executeTurnToolCalls`, which stays serial and is UNCHANGED by this pool).
 *
 * PROBE CONCLUSION (task t-1): @playwright/mcp@0.0.79 (pinned in
 * browser/Dockerfile:59) is judged SUPPORTED for this pool's purpose —
 * several concurrent streamable-HTTP sessions against the one already-running
 * server process, each tracking its own "current tab" independently, all
 * sharing the one persistent `--user-data-dir` Chromium profile.
 *
 * Evidence actually available in this workspace, and its limits:
 *  - No copy of @playwright/mcp ships in this repo — browser/Dockerfile:59
 *    (`RUN npm install -g @playwright/mcp@0.0.79`) installs it at IMAGE BUILD
 *    time, and this workspace has no `agent/node_modules` or `browser`
 *    vendored copy to inspect, nor any way here to run npm/node to fetch or
 *    launch one. This conclusion is therefore NOT verified by direct
 *    inspection of the package or by exercising it.
 *  - browser/entrypoint.sh (the `exec env DISPLAY=... npx @playwright/mcp@0.0.79
 *    --port ... --user-data-dir "$BROWSER_PROFILE_DIR" ...` line at its end)
 *    launches exactly ONE @playwright/mcp process for the container's whole
 *    life, on the persistent profile, with no `--isolated` flag — so every
 *    session this pool opens is a SEPARATE streamable-HTTP client connection
 *    to that SAME already-running process, never a second process launch (a
 *    second process launched against the same `--user-data-dir` would in any
 *    case collide on Chromium's SingletonLock, which entrypoint.sh's own
 *    SingletonLock-adjudication comment describes at length).
 *  - browser/session-server.js's SingletonLock/profile-locking and
 *    open()/close()/evict() machinery (its `createSessionManager`) governs a
 *    DIFFERENT, separate attended-sign-in browser process spawned for the
 *    noVNC viewport, not @playwright/mcp's own session handling — so it
 *    neither confirms nor rules out multi-session support here.
 *  - agent/harness/builtins/harvestTabs.ts's own module doc ("Every browser
 *    call this module makes shares ONE MCP connection to the `browser`
 *    server, and @playwright/mcp's tab tools switch which tab is 'current'
 *    for every OTHER tool") documents today's SINGLE-connection behaviour
 *    only; nothing in this repo documents multi-CONNECTION (multi-session)
 *    behaviour either way.
 *  - The SUPPORTED conclusion instead rests on @playwright/mcp's documented
 *    architecture: its streamable-HTTP transport creates one connection (and
 *    one session-scoped tab-tracking context) per MCP session id, while a
 *    persistent-profile (`--user-data-dir` without `--isolated`) browser
 *    context is opened once and shared/reused across sessions within the
 *    same server process. That is inference from the package's known design
 *    at the time of writing, not something this workspace can independently
 *    confirm — flagged here explicitly rather than presented as a checked
 *    fact.
 *
 * Because the conclusion is inferred rather than verified, this pool is
 * built to fail SAFE if it turns out wrong: every extra session is purely
 * ADDITIVE to the harness's own single shared `browser` connection, never a
 * replacement for it, and any failure to open one degrades the pool to fewer
 * usable sessions — down to zero — rather than ever throwing into the
 * harvest path (see {@link BrowserSessionPool.lease}). At zero or one
 * available session, harvestPostings.ts falls back to its existing
 * tab-per-board/serial paths unchanged.
 */

import type { ConnectedClient, McpClientPool } from './client.js';
import { resolveBrowserSessionCount } from './config.js';

/** The already-configured server name every extra session connects to. */
const BROWSER_SERVER_NAME = 'browser';

/** Minimum extra sessions before the session-per-worker harvest path is
 * worth taking over the tab-per-board fallback — one usable session is not
 * worth the dispatch overhead over the existing tab path, so two is the
 * threshold. Also gates how many sessions this pool ever bothers opening:
 * below this threshold no harvest would ever take the sessions path anyway,
 * so opening even one session would be pure waste — see `ensureOpened` and
 * `openAll`. Exported so harvestPostings.ts's own dispatch-precedence check
 * imports this SAME constant rather than duplicating the number. */
export const MIN_SESSIONS_FOR_PARALLEL_HARVEST = 2;

/** One leased-or-idle extra browser session. */
export interface BrowserSession {
  /** The session's own independent MCP client, connected to `browser`. */
  client: ConnectedClient;
}

/**
 * A FIFO pool of extra MCP sessions to the `browser` server. Connects
 * lazily — nothing opens until the first {@link lease}/{@link availableSessionCount}
 * call — and degrades gracefully: a connect failure simply means fewer
 * sessions are ever handed out, never a thrown error into the harvest path.
 * See this module's own doc for why that safety net matters here.
 */
export class BrowserSessionPool {
  private readonly pool: McpClientPool;
  private readonly maxSessions: number;
  private readonly idle: BrowserSession[] = [];
  private opened = 0;
  private connectPromise?: Promise<void>;

  /**
   * @param pool The harness's own MCP client pool, already connected to the
   *   `browser` server — {@link McpClientPool.connectExtra} opens each extra
   *   session.
   * @param env The environment `AGENT_BROWSER_SESSIONS` is read from.
   */
  constructor(pool: McpClientPool, env: NodeJS.ProcessEnv) {
    this.pool = pool;
    this.maxSessions = resolveBrowserSessionCount(env);
  }

  /**
   * How many extra sessions this pool actually opened (not the configured
   * max) — what a caller like harvestPostings.ts should dispatch against,
   * since a connect failure can leave this lower than the configured
   * `AGENT_BROWSER_SESSIONS` once connecting has run.
   */
  async availableSessionCount(): Promise<number> {
    await this.ensureOpened();
    return this.opened;
  }

  /**
   * Lease one session, opening extra connections lazily on first use (up to
   * `AGENT_BROWSER_SESSIONS`, degrading to fewer on any connect failure).
   * FIFO: a released session re-joins the back of the queue, so leases
   * round-robin fairly across workers. Returns `undefined` when no session
   * is available (configured to 0, every connect attempt failed, or every
   * opened session is currently leased out) — callers must fall back rather
   * than block waiting for one.
   */
  async lease(): Promise<BrowserSession | undefined> {
    await this.ensureOpened();
    return this.idle.shift();
  }

  /** Return a leased session to the pool, for the next {@link lease}. */
  release(session: BrowserSession): void {
    this.idle.push(session);
  }

  /**
   * Permanently remove a LEASED session from the pool instead of returning
   * it to {@link idle} — for a session harvestSessions.ts has confirmed dead
   * (its transport threw, rather than returning a normal `isError` result).
   * Closes the client (swallowing any close error, same as every other close
   * in this module — a failed close must never surface as a harvest
   * failure) and decrements `opened`, so {@link availableSessionCount} stops
   * advertising it and a later harvest naturally degrades to the tab/serial
   * fallbacks once `opened` drops below {@link MIN_SESSIONS_FOR_PARALLEL_HARVEST}.
   */
  async discard(session: BrowserSession): Promise<void> {
    await closeQuietly(session.client);
    this.opened = Math.max(0, this.opened - 1);
  }

  /** Run {@link openAll} exactly once, sharing one in-flight attempt across
   * concurrent callers instead of racing independent connect attempts.
   * Short-circuits below {@link MIN_SESSIONS_FOR_PARALLEL_HARVEST}: nothing
   * is ever opened when `maxSessions` cannot reach the threshold the
   * sessions path itself requires to be worth taking, so e.g.
   * `AGENT_BROWSER_SESSIONS=1` opens zero connections rather than one that
   * would never be used. */
  private ensureOpened(): Promise<void> {
    if (this.maxSessions < MIN_SESSIONS_FOR_PARALLEL_HARVEST) return Promise.resolve();
    if (!this.connectPromise) this.connectPromise = this.openAll();
    return this.connectPromise;
  }

  /** Open extra connections up to `maxSessions`. Stops at the first failure
   * — there is no reason to expect a later attempt to succeed once one has
   * failed — leaving whatever opened successfully before it. When that
   * leaves a PARTIAL result strictly between zero and
   * {@link MIN_SESSIONS_FOR_PARALLEL_HARVEST} (a connect failure partway
   * through), the stragglers are closed and `opened` reset to zero rather
   * than left dangling — a lone idle session below the threshold would never
   * be leased by the sessions path (see `ensureOpened`) but would still sit
   * open, competing with nothing, for no benefit. */
  private async openAll(): Promise<void> {
    for (let i = 0; i < this.maxSessions; i++) {
      const client = await this.tryConnect(i);
      if (!client) break;
      this.idle.push({ client });
      this.opened += 1;
    }
    if (this.opened > 0 && this.opened < MIN_SESSIONS_FOR_PARALLEL_HARVEST) {
      await this.closeStragglers();
    }
  }

  /** Close every currently-idle session (all of them, since this only runs
   * from within {@link openAll}, before any {@link lease} has ever handed
   * one out) and reset `opened` to zero. */
  private async closeStragglers(): Promise<void> {
    const stragglers = this.idle.splice(0, this.idle.length);
    await Promise.all(stragglers.map((s) => closeQuietly(s.client)));
    this.opened = 0;
  }

  /** Attempt one extra connection, logging (never throwing) on failure. */
  private async tryConnect(attemptedIndex: number): Promise<ConnectedClient | undefined> {
    try {
      return await this.pool.connectExtra(BROWSER_SERVER_NAME);
    } catch (err) {
      logDegraded(attemptedIndex, err);
      return undefined;
    }
  }
}

/** Close a session's client, swallowing any close error — a failed close is
 * never this pool's caller's problem, matching every other failure-swallow
 * in this module. */
async function closeQuietly(client: ConnectedClient): Promise<void> {
  try {
    await client.close();
  } catch {
    // Deliberately swallowed — see this function's own doc.
  }
}

/** Emit one structured stderr line when an extra session fails to connect —
 * never page content or credentials, just the pool's own degradation. */
function logDegraded(attemptedIndex: number, err: unknown): void {
  const message = err instanceof Error ? err.message : String(err);
  const line = { event: 'browserSessionPool.degraded', attemptedIndex, error: message };
  process.stderr.write(`${JSON.stringify(line)}\n`);
}
