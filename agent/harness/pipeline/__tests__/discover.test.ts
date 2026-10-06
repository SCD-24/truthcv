import { describe, it, expect, vi } from 'vitest';
import { discover } from '../discover.js';
import { fetchPosting } from '../fetchPosting.js';
import type { BrowserToolCall } from '../../builtins/harvestTypes.js';

/** A snapshot with several Greenhouse links so harvest extraction succeeds. */
const GOOD = '- Page URL: https://x.test\n' + [1, 2].map((n) => `- link "Job ${n}" [ref=e${n}]: https://boards.greenhouse.io/acme/jobs/${n}`).join('\n');

function browser(snapshots: Record<string, string>): BrowserToolCall {
  let current = '';
  return async (tool, args) => {
    if (tool === 'browser_navigate') { current = String(args.url); return { content: 'ok', isError: false }; }
    if (tool === 'browser_snapshot') return { content: snapshots[current] ?? '', isError: false };
    return { content: 'ok', isError: false };
  };
}

const CONFIG = {
  searchQueries: [
    { profile: 'A', profiles: ['A'], source: 'greenhouse.io', query: 'q1', url: 'https://www.google.com/search?q=q1' },
    { profile: 'B', profiles: ['B'], source: 'lever.co', query: 'q2', url: 'https://www.google.com/search?q=q2' },
  ],
  directBoards: [{ url: 'https://board.test/jobs', profiles: [{ profile: 'A', keywords: ['dev'], locations: ['Berlin'] }] }],
  feedPostings: [{ url: 'https://feed.test/1', title: 'Feed job', source: 'rr', profile: 'A' }],
};

describe('discover', () => {
  it('records one coverage per composed query/board and dedupes + filters', async () => {
    const mcp = vi.fn(async (tool: string, args: Record<string, unknown>) => {
      if (tool === 'filter_unscreened_urls') {
        const urls = args.urls as string[];
        return { content: JSON.stringify({ unscreened: urls.filter((u) => !u.endsWith('/2')) }), isError: false };
      }
      return { content: '{"recorded":true}', isError: false };
    });
    const call = browser({
      'https://www.google.com/search?q=q1': GOOD,
      'https://www.google.com/search?q=q2': GOOD,
      'https://board.test/jobs': '- Page URL: https://board.test/jobs\nNo matching jobs found',
    });
    const out = await discover(CONFIG, 'run1', call, mcp, { sleep: async () => {} });
    const cov = mcp.mock.calls.filter((c) => c[0] === 'record_discovery_coverage').map((c) => c[1]);
    expect(cov.filter((c) => c.channel === 'dork')).toHaveLength(2);
    expect(cov.filter((c) => c.channel === 'direct')).toHaveLength(1);
    expect(cov.filter((c) => c.channel === 'feed')).toHaveLength(1);
    expect(cov.every((c) => c.run_id === 'run1')).toBe(true);
    expect(out.coverageComplete).toBe(true);
    const urls = out.candidates.map((c) => c.url);
    expect(urls).toContain('https://boards.greenhouse.io/acme/jobs/1');
    expect(urls).not.toContain('https://boards.greenhouse.io/acme/jobs/2');
    const first = out.candidates.find((c) => c.url.endsWith('/jobs/1'))!;
    expect(first.profiles.sort()).toEqual(['A', 'B']);
    expect(first.channel).toBe('dork');
  });

  it('maps a Google /sorry CAPTCHA to blocked', async () => {
    const mcp = vi.fn(async (_tool: string, _args: Record<string, unknown>) => ({ content: '{"recorded":true}', isError: false }));
    const call = browser({ 'https://www.google.com/search?q=q1': '- Page URL: https://www.google.com/sorry/index\nunusual traffic' });
    await discover({ searchQueries: [CONFIG.searchQueries[0]] }, 'r', call, mcp);
    const cov = mcp.mock.calls.find((c) => c[0] === 'record_discovery_coverage')![1] as Record<string, unknown>;
    expect(cov.status).not.toBe('searched');
    expect(['blocked', 'extraction_failed']).toContain(cov.status);
  });

  it('reports incomplete coverage when recording fails', async () => {
    const mcp = vi.fn(async (_tool: string, _args: Record<string, unknown>) => ({ content: 'boom', isError: true }));
    const out = await discover({ searchQueries: [CONFIG.searchQueries[0]] }, 'r', browser({}), mcp);
    expect(out.coverageComplete).toBe(false);
  });
});

describe('discover dork pacing', () => {
  const SORRY = '- Page URL: https://www.google.com/sorry/index\nunusual traffic';
  const dorks = (n: number) => ({
    searchQueries: Array.from({ length: n }, (_, i) => ({ profiles: ['A'], source: 'g', query: `q${i}`, url: `https://www.google.com/search?q=q${i}` })),
  });
  const okMcp = () => vi.fn(async (_t: string, _a: Record<string, unknown>) => ({ content: '{"recorded":true}', isError: false }));
  const covs = (m: ReturnType<typeof okMcp>) => m.mock.calls.filter((c) => c[0] === 'record_discovery_coverage').map((c) => c[1]);

  const sleeps = async (random?: () => number) => {
    const sleep = vi.fn(async (_ms: number) => {});
    await discover(dorks(3), 'r', browser({}), okMcp(), { sleep, random });
    return sleep.mock.calls.map((c) => c[0]);
  };

  it('sleeps the minimum between dorks (N-1 times) when random is 0', async () => {
    expect(await sleeps(() => 0)).toEqual([4000, 4000]);
  });

  it('sleeps the maximum when random is just below 1', async () => {
    expect(await sleeps(() => 0.999999)).toEqual([7000, 7000]);
  });

  it('draws a fresh delay per gap', async () => {
    const seq = [0, 0.5];
    let i = 0;
    expect(await sleeps(() => seq[i++])).toEqual([4000, 5500]);
  });

  it('default random yields integer delays within [4000, 7000]', async () => {
    const s = await sleeps();
    expect(s).toHaveLength(2);
    for (const ms of s) {
      expect(Number.isInteger(ms)).toBe(true);
      expect(ms).toBeGreaterThanOrEqual(4000);
      expect(ms).toBeLessThanOrEqual(7000);
    }
  });

  it('skips remaining dorks after 2 consecutive Google blocks', async () => {
    const navigated: string[] = [];
    const inner = browser({ 'https://www.google.com/search?q=q0': SORRY, 'https://www.google.com/search?q=q1': SORRY });
    const call: BrowserToolCall = async (tool, args) => {
      if (tool === 'browser_navigate') navigated.push(String(args.url));
      return inner(tool, args);
    };
    const mcp = okMcp();
    await discover(dorks(3), 'r', call, mcp, { sleep: async () => {} });
    expect(navigated).not.toContain('https://www.google.com/search?q=q2');
    const c = covs(mcp);
    expect(c).toHaveLength(3);
    expect(c[0].status).toBe('blocked');
    expect(c[2]).toMatchObject({ status: 'skipped', postings_found: 0 });
  });

  it('resets the block counter after a success', async () => {
    const call = browser({ 'https://www.google.com/search?q=q0': SORRY, 'https://www.google.com/search?q=q1': GOOD, 'https://www.google.com/search?q=q2': SORRY });
    const mcp = okMcp();
    await discover(dorks(4), 'r', call, mcp, { sleep: async () => {} });
    expect(covs(mcp).some((c) => c.status === 'skipped')).toBe(false);
  });
});

describe('fetchPosting', () => {
  it('returns readable text', async () => {
    const text = 'Senior engineer role. '.repeat(30);
    const r = await fetchPosting(browser({ 'https://p.test/1': text }), 'https://p.test/1');
    expect(r.unreadable).toBeFalsy();
  });

  it('marks a near-empty page unreadable', async () => {
    const r = await fetchPosting(browser({ 'https://p.test/1': 'x' }), 'https://p.test/1');
    expect(r).toMatchObject({ unreadable: true, blocker: 'unreadable' });
  });
});
