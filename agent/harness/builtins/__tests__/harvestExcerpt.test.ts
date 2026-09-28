import { describe, expect, it } from 'vitest';
import { compactSnapshot, fitRawSnapshots } from '../harvestExcerpt.js';
import type { HarvestBoardResult } from '../harvestTypes.js';

const FILLER = '- generic "x": lorem ipsum filler text here\n'.repeat(500);

function bigSnapshot(): string {
  const links = [1, 2, 3].map((n) => `- link "Job ${n}" [ref=e${n}]:\n  - /url: https://a.example/job/${n}\n`).join('');
  return `- Page URL: https://a.example/\n${FILLER}${links}${FILLER}`;
}

describe('compactSnapshot', () => {
  it('leaves a small snapshot unchanged', () => {
    expect(compactSnapshot('hello', 100)).toEqual({ text: 'hello', truncated: false, omittedChars: 0 });
  });
  it('keeps links and URL lines and drops filler', () => {
    const out = compactSnapshot(bigSnapshot(), 2000);
    expect(out.truncated).toBe(true);
    expect(out.text).toContain('Page URL: https://a.example/');
    for (const n of [1, 2, 3]) {
      expect(out.text).toContain(`link "Job ${n}"`);
      expect(out.text).toContain(`/url: https://a.example/job/${n}`);
    }
    expect(out.text).not.toContain('lorem');
    expect(out.omittedChars).toBeGreaterThan(0);
  });
});

describe('fitRawSnapshots', () => {
  it('keeps all boards under budget', () => {
    const results: HarvestBoardResult[] = Array.from({ length: 10 }, (_, i) => ({
      board: `b${i}`, url: 'https://a.example/', outcome: 'needs_review', tier: '', postings: [], note: 'n',
      rawSnapshot: bigSnapshot() + 'x'.repeat(20000),
    }));
    const fitted = fitRawSnapshots(results, 24000);
    expect(fitted).toHaveLength(10);
    expect(JSON.stringify({ results: fitted }).length).toBeLessThan(24000);
    expect(fitted.every((r) => r.rawSnapshotTruncated)).toBe(true);
  });
  it('stays within budget for escape-heavy snapshots', () => {
    const line = '- link "a\\"b\\\\c" [ref=e1]:\n  - /url: https://a.example/j?q=\\"\\\\\n';
    const results: HarvestBoardResult[] = Array.from({ length: 10 }, (_, i) => ({
      board: `b${i}`, url: 'https://a.example/', outcome: 'needs_review', tier: '', postings: [], note: 'n',
      rawSnapshot: line.repeat(Math.ceil(20000 / line.length)),
    }));
    const fitted = fitRawSnapshots(results, 24000);
    expect(fitted).toHaveLength(10);
    expect(JSON.stringify({ results: fitted }).length).toBeLessThanOrEqual(24000);
  });
  it('omits snapshots when no room', () => {
    const results: HarvestBoardResult[] = [{
      board: 'b', url: 'u', outcome: 'needs_review', tier: '', postings: [], note: 'n', rawSnapshot: 'x'.repeat(5000),
    }];
    const fitted = fitRawSnapshots(results, 100);
    expect(fitted[0].rawSnapshot).toBeUndefined();
    expect(fitted[0].note).toContain('omitted');
  });
});
