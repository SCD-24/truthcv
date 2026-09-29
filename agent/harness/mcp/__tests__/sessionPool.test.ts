import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { McpClientPool, type ClientConnector, type ConnectedClient } from '../client.js';
import { BrowserSessionPool } from '../sessionPool.js';

/** A network-free fake session, distinguishable by `id`. */
function fakeSession(id: number): ConnectedClient {
  return {
    listTools: async () => ({ tools: [] }),
    callTool: async () => ({ content: [{ type: 'text', text: `session-${id}` }], isError: false }),
    close: async () => {},
  };
}

/** Same as {@link fakeSession}, but records its own id into `closed` when
 * closed — lets a test assert exactly which sessions got torn down. */
function trackedSession(id: number, closed: number[]): ConnectedClient {
  return {
    listTools: async () => ({ tools: [] }),
    callTool: async () => ({ content: [{ type: 'text', text: `session-${id}` }], isError: false }),
    close: async () => {
      closed.push(id);
    },
  };
}

/** Silence the pool's own `browserSessionPool.degraded` stderr line — the
 * degradation tests below assert on the pool's return values, not stderr. */
beforeEach(() => {
  vi.spyOn(process.stderr, 'write').mockImplementation(() => true);
});
afterEach(() => {
  vi.restoreAllMocks();
});

/** One already-constructed `McpClientPool` with a `browser` server entry,
 * whose extra connections all go through `connector`. Never calls
 * `connectAll` — {@link BrowserSessionPool} only ever uses `connectExtra`,
 * which needs no prior connection of the pool's own. */
function poolWith(connector: ClientConnector): McpClientPool {
  return new McpClientPool([{ name: 'browser', url: 'http://browser' }], connector);
}

describe('BrowserSessionPool', () => {
  it('opens up to AGENT_BROWSER_SESSIONS extra connections, lazily on first use', async () => {
    let connects = 0;
    const pool = poolWith(async () => {
      connects += 1;
      return fakeSession(connects);
    });
    const sessions = new BrowserSessionPool(pool, { AGENT_BROWSER_SESSIONS: '3' });

    expect(connects).toBe(0);
    expect(await sessions.availableSessionCount()).toBe(3);
    expect(connects).toBe(3);
    // A second call reuses the already-opened sessions rather than reconnecting.
    expect(await sessions.availableSessionCount()).toBe(3);
    expect(connects).toBe(3);
  });

  it('defaults AGENT_BROWSER_SESSIONS to 3 when unset', async () => {
    let connects = 0;
    const pool = poolWith(async () => {
      connects += 1;
      return fakeSession(connects);
    });
    const sessions = new BrowserSessionPool(pool, {});

    expect(await sessions.availableSessionCount()).toBe(3);
  });

  it('leases and releases sessions FIFO', async () => {
    let connects = 0;
    const pool = poolWith(async () => {
      connects += 1;
      return fakeSession(connects);
    });
    const sessions = new BrowserSessionPool(pool, { AGENT_BROWSER_SESSIONS: '2' });

    const a = await sessions.lease();
    const b = await sessions.lease();
    expect(a).toBeDefined();
    expect(b).toBeDefined();
    expect(await sessions.lease()).toBeUndefined(); // both leased out already

    sessions.release(a!);
    sessions.release(b!);
    // FIFO: whichever was released FIRST comes back out first.
    expect(await sessions.lease()).toBe(a);
    expect(await sessions.lease()).toBe(b);
  });

  it('degrades all the way to zero — closing the straggler — when a later connect attempt fails and leaves a partial result below the parallel-harvest threshold, never throwing', async () => {
    const closed: number[] = [];
    let calls = 0;
    const pool = poolWith(async () => {
      calls += 1;
      if (calls === 2) throw new Error('connect refused');
      return trackedSession(calls, closed);
    });
    const sessions = new BrowserSessionPool(pool, { AGENT_BROWSER_SESSIONS: '3' });

    await expect(sessions.availableSessionCount()).resolves.toBe(0);
    expect(closed).toEqual([1]);
  });

  it('degrades all the way to zero, without throwing, when every connect attempt fails', async () => {
    const pool = poolWith(async () => {
      throw new Error('connect refused');
    });
    const sessions = new BrowserSessionPool(pool, { AGENT_BROWSER_SESSIONS: '3' });

    await expect(sessions.availableSessionCount()).resolves.toBe(0);
    await expect(sessions.lease()).resolves.toBeUndefined();
  });

  it('never opens any session when AGENT_BROWSER_SESSIONS is 0', async () => {
    let connects = 0;
    const pool = poolWith(async () => {
      connects += 1;
      return fakeSession(connects);
    });
    const sessions = new BrowserSessionPool(pool, { AGENT_BROWSER_SESSIONS: '0' });

    expect(await sessions.availableSessionCount()).toBe(0);
    expect(connects).toBe(0);
    expect(await sessions.lease()).toBeUndefined();
  });

  it('never opens any session when AGENT_BROWSER_SESSIONS is 1 — one session is never worth opening', async () => {
    let connects = 0;
    const pool = poolWith(async () => {
      connects += 1;
      return fakeSession(connects);
    });
    const sessions = new BrowserSessionPool(pool, { AGENT_BROWSER_SESSIONS: '1' });

    expect(await sessions.availableSessionCount()).toBe(0);
    expect(connects).toBe(0);
  });

  it('discard closes the client and shrinks availableSessionCount, without returning it to idle', async () => {
    const closed: number[] = [];
    let connects = 0;
    const pool = poolWith(async () => {
      connects += 1;
      return trackedSession(connects, closed);
    });
    const sessions = new BrowserSessionPool(pool, { AGENT_BROWSER_SESSIONS: '3' });

    expect(await sessions.availableSessionCount()).toBe(3);
    const leased = await sessions.lease();
    expect(leased).toBeDefined();

    await sessions.discard(leased!);

    expect(closed).toEqual([1]);
    expect(await sessions.availableSessionCount()).toBe(2);
  });
});
