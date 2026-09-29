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

describe('compactSnapshot priority budget', () => {
  it('keeps the Page URL and zero-hit line despite 200 nav links', () => {
    const nav = Array.from({ length: 200 }, () => '- link "Images":\n  - /url: https://www.google.com/imghp\n').join('');
    const s = `- Page URL: https://www.google.com/search?q=x\n${nav}Your search - x - did not match any documents.\n`;
    const out = compactSnapshot(s, 2000);
    expect(out.text).toContain('Page URL: https://www.google.com/search?q=x');
    expect(out.text).toContain('did not match any documents');
    expect(out.text.length).toBeLessThanOrEqual(2000);
  });

  it('keeps /url children with their link, not as orphan priority lines', () => {
    const links = Array.from({ length: 200 }, (_, i) => `- link "Engineer ${i}":\n  - /url: https://acme.com/jobs/${i}\n`).join('');
    const out = compactSnapshot(`- Page URL: https://acme.com/jobs\n${links}`, 2000);
    const lines = out.text.split('\n');
    const urlLines = lines.filter((l) => l.includes('/url:')).length;
    const linkLines = lines.filter((l) => l.startsWith('- link')).length;
    expect(linkLines).toBeGreaterThan(0);
    expect(urlLines).toBe(linkLines);
  });

  it('keeps the Page URL even when result-text lines precede it', () => {
    const out = compactSnapshot(`${'- text: jobs\n'.repeat(10)}- Page URL: https://a.example/\n`, 100);
    expect(out.text).toContain('Page URL: https://a.example/');
  });

  it('result-text lines cannot crowd out an early job link', () => {
    const link = '- link "Engineer":\n  - /url: https://acme.com/jobs/1\n';
    const filler = '- text: jobs open for engineering positions\n'.repeat(300);
    const out = compactSnapshot(`- Page URL: https://acme.com/careers\n${link}${filler}`, 6000);
    expect(out.text).toContain('https://acme.com/jobs/1');
    expect(out.text.length).toBeLessThanOrEqual(6000);
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
