import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { McpClientPool, type ClientConnector, type ConnectedClient } from '../../mcp/client.js';
import { BrowserSessionPool } from '../../mcp/sessionPool.js';
import { harvestWithSessions } from '../harvestSessions.js';
import type { HarvestBoardRequest } from '../harvestTypes.js';

/** Silence the pool's own degradation stderr line and harvest's mode line
 * around every test. */
beforeEach(() => {
  vi.spyOn(process.stderr, 'write').mockImplementation(() => true);
});
afterEach(() => {
  vi.restoreAllMocks();
});

/** A greenhouse-shaped posting link for board index `i`, distinguishable by
 * its own job id and title — lets a test confirm a board's OWN posting came
 * back, not some other board's, even when boards share sessions over time. */
function greenhouseLink(i: number): string {
  return `- link "Job ${i}" [ref=e1]: https://boards.greenhouse.io/acme/jobs/${1000 + i}`;
}

/** `count` boards, each with a distinct URL; `keywordIndices` names which
 * ones also carry keywords, to exercise the search-box path. */
function boards(count: number, keywordIndices: number[] = []): HarvestBoardRequest[] {
  return Array.from({ length: count }, (_, i) => ({
    board: `Board${i}`,
    url: `https://board${i}.example/jobs`,
    ...(keywordIndices.includes(i) ? { keywords: `engineer${i}` } : {}),
  }));
}

/** The board index encoded in one of {@link boards}' own URLs. */
function boardIndexFromUrl(url: string): number {
  return Number(/board(\d+)\./.exec(url)?.[1] ?? -1);
}

/** Build a `BrowserSessionPool` of `sessionCount` fake sessions over a
 * network-free connector. Each session tracks its OWN "current url" —
 * mirroring the per-session tab independence sessionPool.ts's probe rests
 * on — set by whichever board it last navigated, and used to answer that
 * board's own `browser_snapshot`.
 *
 * @param navigateDelayMs Per-url artificial delay, so a test can stagger
 *   completion order away from request order.
 * @param failUrl A url whose `browser_navigate` throws, for failure
 *   containment tests.
 * @param keywordUrls Urls that must see a search-box snapshot before their
 *   final one, for the keyword-search-path test.
 */
function fakeSessionPool(
  sessionCount: number,
  navigateDelayMs: (url: string) => number = () => 0,
  failUrl?: string,
  keywordUrls: Set<string> = new Set(),
): { pool: BrowserSessionPool; maxActive: () => number; typeCalls: { url: string; text: string }[] } {
  let active = 0;
  let maxActive = 0;
  const searchShown = new Set<string>();
  const typeCalls: { url: string; text: string }[] = [];
  const connector: ClientConnector = async (): Promise<ConnectedClient> => {
    let currentUrl = '';
    return {
      listTools: async () => ({ tools: [] }),
      callTool: async (params) => {
        const args = params.arguments ?? {};
        if (params.name === 'browser_navigate') {
          const url = args.url as string;
          if (url === failUrl) throw new Error(`transport exploded for ${url}`);
          active += 1;
          maxActive = Math.max(maxActive, active);
          await new Promise((r) => setTimeout(r, navigateDelayMs(url)));
          active -= 1;
          currentUrl = url;
          return { content: [{ type: 'text', text: 'ok' }], isError: false };
        }
        if (params.name === 'browser_snapshot') {
          if (keywordUrls.has(currentUrl) && !searchShown.has(currentUrl)) {
            searchShown.add(currentUrl);
            return { content: [{ type: 'text', text: '- searchbox "Search" [ref=e5]' }], isError: false };
          }
          return { content: [{ type: 'text', text: greenhouseLink(boardIndexFromUrl(currentUrl)) }], isError: false };
        }
        if (params.name === 'browser_type') {
          typeCalls.push({ url: currentUrl, text: args.text as string });
          return { content: [{ type: 'text', text: 'ok' }], isError: false };
        }
        return { content: [{ type: 'text', text: 'ok' }], isError: false };
      },
      close: async () => {},
    };
  };
  const mcpPool = new McpClientPool([{ name: 'browser', url: 'http://browser' }], connector);
  const pool = new BrowserSessionPool(mcpPool, { AGENT_BROWSER_SESSIONS: String(sessionCount) });
  return { pool, maxActive: () => maxActive, typeCalls };
}

describe('harvestWithSessions', () => {
  it('runs at most sessionCount boards concurrently, landing results in request order', async () => {
    // Board 0 is slow; the rest are fast, so completion order scrambles well
    // away from request order while the pool is still bounded to 3 workers.
    const { pool, maxActive } = fakeSessionPool(3, (url) => (boardIndexFromUrl(url) === 0 ? 30 : 5));
    const requested = boards(5);

    const sessionCount = await pool.availableSessionCount();
    const results = await harvestWithSessions(pool, requested, sessionCount);

    expect(results.map((r) => r!.board)).toEqual(['Board0', 'Board1', 'Board2', 'Board3', 'Board4']);
    expect(results.every((r) => r!.outcome === 'searched' && r!.tier === 'harvest')).toBe(true);
    expect(results[3]!.postings[0].title).toBe('Job 3');
    expect(maxActive()).toBe(3);
  });

  it("confines one board's thrown transport failure to its own result", async () => {
    // One session per board (5 of 5) so the worker whose session gets
    // discarded (see the dedicated discard test below) never needs to
    // re-lease mid-harvest — this test is about failure containment, not
    // the sessionCount-bounded-concurrency case the first test above covers.
    const failUrl = 'https://board2.example/jobs';
    const { pool } = fakeSessionPool(5, undefined, failUrl);
    const requested = boards(5);

    const sessionCount = await pool.availableSessionCount();
    const results = await harvestWithSessions(pool, requested, sessionCount);

    expect(results).toHaveLength(5);
    results.forEach((r, i) => expect(r!.board).toBe(`Board${i}`));
    const failed = results[2]!;
    expect(failed.outcome).toBe('blocked');
    expect(failed.note).toContain('transport exploded');
    expect(failed.blockKind).toBeUndefined();
    const others = results.filter((_, i) => i !== 2);
    expect(others.every((r) => r!.outcome === 'searched')).toBe(true);
  });

  it('confines one dead session to its own board without cascading fabricated blocked results onto every remaining board', async () => {
    // Fewer sessions (3) than boards (5): the dead worker's discard+re-lease
    // races the still-busy survivors, so a buggy re-lease-per-board loop
    // would see pool.lease() return undefined at microtask speed and drain
    // every remaining index into a fabricated 'no browser session available'
    // blockedResult. With the fix, only board 2 (the one actually on the
    // dead session) fails; boards 0, 1, 3 and 4 are still genuinely
    // harvested by the two surviving workers, which keep claiming the
    // shared `next` index regardless of which worker exited early.
    const failUrl = 'https://board2.example/jobs';
    const { pool } = fakeSessionPool(3, undefined, failUrl);
    const requested = boards(5);

    const sessionCount = await pool.availableSessionCount();
    expect(sessionCount).toBe(3);
    const results = await harvestWithSessions(pool, requested, sessionCount);

    expect(results).toHaveLength(5);
    results.forEach((r, i) => expect(r?.board).toBe(`Board${i}`));
    expect(results[2]?.outcome).toBe('blocked');
    expect(results[2]?.note).toContain('transport exploded');
    [0, 1, 3, 4].forEach((i) => {
      expect(results[i]?.outcome).toBe('searched');
    });

    expect(await pool.availableSessionCount()).toBe(2);
  });

  it('discards, rather than reuses, a session whose callTool THREW — availableSessionCount drops afterward', async () => {
    const failUrl = 'https://board2.example/jobs';
    const { pool } = fakeSessionPool(3, undefined, failUrl);
    const requested = boards(5);

    const sessionCount = await pool.availableSessionCount();
    expect(sessionCount).toBe(3);
    await harvestWithSessions(pool, requested, sessionCount);

    // The session whose transport threw was discarded, not released back to
    // idle — availableSessionCount now reflects one fewer opened session.
    expect(await pool.availableSessionCount()).toBe(sessionCount - 1);
  });

  it('refuses a denied browser tool without ever invoking the session client, matching the tab path', async () => {
    const calls: string[] = [];
    const connector: ClientConnector = async () => ({
      listTools: async () => ({ tools: [] }),
      callTool: async (params) => {
        calls.push(params.name);
        return { content: [{ type: 'text', text: 'ok' }], isError: false };
      },
      close: async () => {},
    });
    const mcpPool = new McpClientPool([{ name: 'browser', url: 'http://browser' }], connector);
    const pool = new BrowserSessionPool(mcpPool, { AGENT_BROWSER_SESSIONS: '2' });
    const requested = boards(1);
    const isPermitted = (toolName: string): string | undefined =>
      toolName === 'browser_navigate' ? "Tool 'browser_navigate' is not permitted by the allow-list." : undefined;

    const sessionCount = await pool.availableSessionCount();
    const results = await harvestWithSessions(pool, requested, sessionCount, isPermitted);

    expect(results[0]!.outcome).toBe('blocked');
    expect(results[0]!.note).toContain('not permitted');
    expect(calls).toEqual([]);
  });

  it('types keywords into the detected search box before the final snapshot', async () => {
    const keywordUrl = 'https://board0.example/jobs';
    const { pool, typeCalls } = fakeSessionPool(2, undefined, undefined, new Set([keywordUrl]));
    const requested = boards(2, [0]);

    const sessionCount = await pool.availableSessionCount();
    const results = await harvestWithSessions(pool, requested, sessionCount);

    expect(typeCalls).toEqual([{ url: keywordUrl, text: 'engineer0' }]);
    expect(results[0]!.outcome).toBe('searched');
    expect(results[0]!.postings[0].title).toBe('Job 0');
  });

  it('runs at most one worker per board when boards are fewer than sessions', async () => {
    const { pool, maxActive } = fakeSessionPool(5, () => 5);
    const requested = boards(2);

    const sessionCount = await pool.availableSessionCount();
    const results = await harvestWithSessions(pool, requested, sessionCount);

    expect(results).toHaveLength(2);
    expect(maxActive()).toBe(2);
  });
});
