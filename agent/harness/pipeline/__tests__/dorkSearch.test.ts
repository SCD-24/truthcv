import { describe, expect, it, vi } from 'vitest';
import { GOOGLE_COOLDOWN_MS, searchDorks, type DorkSearchDeps, type Lock } from '../dorkSearch.js';
import { defaultDorkState, type DorkState } from '../dorkState.js';
import { discover } from '../discover.js';
import type { BrowserToolCall } from '../../builtins/harvestTypes.js';

const GOOD = '- Page URL: https://x.test\n' + [1, 2].map((n) => `- link "Job ${n}" [ref=e${n}]: https://boards.greenhouse.io/acme/jobs/${n}`).join('\n');
const SORRY = '- Page URL: https://www.google.com/sorry/index\nunusual traffic';
const NOW = 5_000_000;
const url = (i: number) => `https://www.google.com/search?q=q${i}`;
const reqs = (n: number) => Array.from({ length: n }, (_, i) => ({ board: `g: q${i}`, url: url(i) }));

function browser(snaps: Record<string, string>, navigated: string[] = []): BrowserToolCall {
  let current = '';
  return async (tool, args) => {
    if (tool === 'browser_navigate') { current = String(args.url); navigated.push(current); }
    if (tool === 'browser_snapshot') return { content: snaps[current] ?? '', isError: false };
    return { content: 'ok', isError: false };
  };
}

function deps(over: Partial<DorkSearchDeps> & { state?: DorkState }): DorkSearchDeps {
  return { call: browser({}), sleep: async () => {}, random: () => 0, now: () => NOW, lock: (fn) => fn(), state: defaultDorkState(), errors: [], ...over };
}

describe('searchDorks', () => {
  it('measures pacing from the persisted lastSearchAt', async () => {
    const sleep = vi.fn(async (_ms: number) => {});
    const state = { ...defaultDorkState(), lastSearchAt: NOW - 5000 };
    await searchDorks(reqs(2), deps({ sleep, state }));
    expect(sleep.mock.calls.map((c) => c[0])).toEqual([10000, 15000]);
    expect(state.lastSearchAt).toBe(NOW);
  });

  it('does not sleep when the pacing interval already passed', async () => {
    const sleep = vi.fn(async (_ms: number) => {});
    await searchDorks(reqs(1), deps({ sleep, state: { ...defaultDorkState(), lastSearchAt: NOW - 60_000 } }));
    expect(sleep).not.toHaveBeenCalled();
  });

  it('sleeps outside the browser lock', async () => {
    let held = false;
    const lock: Lock = async (fn) => { held = true; try { return await fn(); } finally { held = false; } };
    const heldDuringSleep: boolean[] = [];
    const sleep = async () => { heldDuringSleep.push(held); };
    await searchDorks(reqs(2), deps({ lock, sleep }));
    expect(heldDuringSleep).toEqual([false]);
  });

  it('starts a 30 minute cooldown after 2 blocks and defers the rest', async () => {
    const navigated: string[] = [];
    const state = defaultDorkState();
    const out = await searchDorks(reqs(4), deps({ call: browser({ [url(0)]: SORRY, [url(1)]: SORRY }, navigated), state }));
    expect(out[0].r?.outcome).toBe('blocked');
    const until = new Date(NOW + GOOGLE_COOLDOWN_MS).toISOString();
    expect(out[2].deferredReason).toBe(`not searched: Google CAPTCHA (/sorry) on 2 searches in a row; Google search paused until ${until}; queued first for the next run`);
    expect(out[3].deferredReason).toBeTruthy();
    expect(navigated).not.toContain(url(2));
    expect(state.cooldownUntil).toBe(NOW + GOOGLE_COOLDOWN_MS);
    expect(state.deferred).toEqual(['g: q0', 'g: q1', 'g: q2', 'g: q3']);
  });

  it('names the consent page when the last block was a consent interstitial', async () => {
    const consent = '- Page URL: https://consent.google.com/m\nBefore you continue to Google';
    const out = await searchDorks(reqs(3), deps({ call: browser({ [url(0)]: consent, [url(1)]: consent }) }));
    const until = new Date(NOW + GOOGLE_COOLDOWN_MS).toISOString();
    expect(out[2].deferredReason).toBe(`not searched: Google consent page could not be passed on 2 searches in a row; Google search paused until ${until}; queued first for the next run`);
  });

  it('persists cooldown and blocked+remaining pending after every search (crash-safe)', async () => {
    const saved: DorkState[] = [];
    const saveState = async (s: DorkState) => { saved.push({ ...s, deferred: [...s.deferred] }); return undefined; };
    await searchDorks(reqs(4), deps({ call: browser({ [url(0)]: SORRY, [url(1)]: SORRY }), saveState }));
    expect(saved[1].cooldownUntil).toBe(NOW + GOOGLE_COOLDOWN_MS);
    expect(saved[1].deferred).toEqual(['g: q0', 'g: q1', 'g: q2', 'g: q3']);
  });

  it('drops successfully searched dorks from the persisted pending list', async () => {
    const saved: string[][] = [];
    const saveState = async (s: DorkState) => { saved.push([...s.deferred]); return undefined; };
    await searchDorks(reqs(2), deps({ call: browser({ [url(0)]: GOOD, [url(1)]: GOOD }), saveState }));
    expect(saved[0]).toEqual(['g: q1']);
    expect(saved[saved.length - 1]).toEqual([]);
  });

  it('defers everything while a persisted cooldown is active, then searches after it expires', async () => {
    const navigated: string[] = [];
    const active = { ...defaultDorkState(), cooldownUntil: NOW + 1000 };
    const out = await searchDorks(reqs(2), deps({ call: browser({}, navigated), state: active }));
    const until = new Date(NOW + 1000).toISOString();
    expect(out.map((o) => o.deferredReason)).toEqual(Array(2).fill(`not searched: Google search paused until ${until} after repeated blocks; queued first for the next run`));
    expect(navigated).toEqual([]);
    const expired = { ...defaultDorkState(), cooldownUntil: NOW - 1 };
    const out2 = await searchDorks(reqs(1), deps({ call: browser({ [url(0)]: GOOD }), state: expired }));
    expect(out2[0].r?.outcome).toBe('searched');
  });

  it('persists state after each search and reports save errors', async () => {
    const saved: DorkState[] = [];
    const errors: string[] = [];
    await searchDorks(reqs(1), deps({ errors, saveState: async (s) => { saved.push({ ...s }); return 'nope'; } }));
    expect(saved.length).toBeGreaterThan(0);
    expect(errors).toContain('nope');
  });
});

describe('discover pending-first ordering', () => {
  it('searches previously deferred queries first and passes batches to onCandidates', async () => {
    const navigated: string[] = [];
    const cfg = { searchQueries: [0, 1].map((i) => ({ profiles: ['A'], source: 'g', query: `q${i}`, url: url(i) })) };
    const state = { ...defaultDorkState(), deferred: ['g: q1'] };
    const batches: string[][] = [];
    const mcp = vi.fn(async () => ({ content: '{"recorded":true}', isError: false }));
    await discover(cfg, 'r', browser({ [url(0)]: GOOD, [url(1)]: GOOD }, navigated), mcp, {
      sleep: async () => {}, now: () => NOW, dorkState: state, onCandidates: async (b) => void batches.push(b.map((c) => c.url)),
    });
    expect(navigated.indexOf(url(1))).toBeLessThan(navigated.indexOf(url(0)));
    expect(batches).toHaveLength(2);
    expect(state.deferred).toEqual([]);
  });
});
