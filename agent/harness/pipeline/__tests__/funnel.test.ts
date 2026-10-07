import { describe, it, expect, vi } from 'vitest';
import { buildFunnel, recordFunnel, FUNNEL_OUTCOMES } from '../funnel.js';
import type { Candidate } from '../types.js';

const G = { source: 'g', channel: 'dork' } as const;
const F = { source: 'rr', channel: 'feed' } as const;
const cand = (n: number, sources: Candidate['sources']): Candidate => ({ url: `https://a.test/${n}`, title: 't', channel: 'dork', profiles: [], sources });

describe('buildFunnel', () => {
  const all = [cand(1, [G, F]), cand(2, [G]), cand(3, [F]), cand(4, [G]), cand(5, [G])];
  const funnel = buildFunnel(
    all,
    [{ url: 'https://a.test/2', reason: 'previously_screened', sources: [G] }, { url: 'https://a.test/3', reason: 'duplicate', duplicate_of: 'https://a.test/1', sources: [F] }],
    [{ url: 'https://a.test/1', outcome: 'for_review', detail: 'P' }, { url: 'https://a.test/4', outcome: 'rejected', detail: 'x' }],
  );

  it('gives each URL exactly one outcome, defaulting to failed', () => {
    expect(funnel.urls.map((u) => u.outcome)).toEqual(['for_review', 'previously_screened', 'duplicate', 'rejected', 'failed']);
    expect(funnel.urls[2].detail).toBe('duplicate of https://a.test/1');
    expect(funnel.urls[4].detail).toBe('no outcome recorded');
  });

  it('counts a URL in every source row and balances', () => {
    const g = funnel.sources.find((s) => s.source === 'g')!;
    const f = funnel.sources.find((s) => s.source === 'rr')!;
    expect(g).toMatchObject({ postings_seen: 4, for_review: 1, previously_screened: 1, rejected: 1, failed: 1 });
    expect(f).toMatchObject({ postings_seen: 2, for_review: 1, duplicate: 1 });
    for (const r of [...funnel.sources, funnel.totals]) expect(FUNNEL_OUTCOMES.reduce((n, k) => n + r[k], 0)).toBe(r.postings_seen);
    expect(funnel.totals.postings_seen).toBe(all.length);
  });
});

describe('recordFunnel', () => {
  const f = buildFunnel([], [], []);
  it('returns mismatches, ignores truncation, reports call errors', async () => {
    const mk = (content: string, isError = false) => vi.fn(async () => ({ content, isError }));
    expect(await recordFunnel(mk('{"recorded":true,"mismatches":["m"],"truncated":true}'), 'r', f)).toEqual(['source funnel mismatch: m']);
    expect(await recordFunnel(mk('{"recorded":true,"mismatches":[],"truncated":true}'), 'r', f)).toEqual([]);
    expect(await recordFunnel(mk('{"recorded":false}'), 'r', f)).toEqual(['source funnel not recorded: server refused (recorded:false)']);
    expect(await recordFunnel(mk('boom', true), 'r', f)).toEqual(['source funnel not recorded: boom']);
    expect(await recordFunnel(vi.fn(async () => { throw new Error('x'); }), 'r', f)).toEqual(['source funnel failed: x']);
  });
});
