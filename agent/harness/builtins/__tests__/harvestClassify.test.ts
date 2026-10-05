import { describe, expect, it } from 'vitest';
import { classifySnapshot, isExplicitlyEmpty } from '../harvestClassify.js';

describe('classifySnapshot German empty phrasing', () => {
  it('classifies a German zero-result page as empty', () => {
    const board = { board: 'Acme DE', url: 'https://acme.example/jobs' };
    const snapshot = 'Keine Ergebnisse gefunden für Ihre Suche.';
    const result = classifySnapshot(board, snapshot);
    expect(result.outcome).toBe('empty');
    expect(result.postings).toEqual([]);
  });
});

describe('classifySnapshot dorks and excerpts', () => {
  it('extracts site: target links from a Google SERP', () => {
    const url = 'https://www.google.com/search?q=site:careers.example.org+engineer';
    const snapshot = [
      `- Page URL: ${url}`,
      '- link "Engineer at Acme" [ref=e1]:',
      '  - /url: https://careers.example.org/x',
      '- link "Images" [ref=e2]:',
      '  - /url: https://www.google.com/imghp',
    ].join('\n');
    const result = classifySnapshot({ board: 'Dork', url }, snapshot);
    expect(result.outcome).toBe('searched');
    expect(result.postings[0].ats).toBe('dork-site');
    expect(result.note).toContain("dork's site");
  });

  it('caps an oversized needs_review snapshot', () => {
    const board = { board: 'Big', url: 'https://big.example/jobs' };
    const snapshot = '- generic: filler text line\n'.repeat(1000);
    const result = classifySnapshot(board, snapshot);
    expect(result.outcome).toBe('needs_review');
    expect(result.rawSnapshotTruncated).toBe(true);
    expect((result.rawSnapshot ?? '').length).toBeLessThanOrEqual(6000);
  });
});

describe('classifySnapshot Google SERP/interstitials', () => {
  const serpUrl = 'https://www.google.com/search?q=site:jobs.lever.co+engineer';
  const nav = [
    '- link "Images" [ref=e1]:', '  - /url: https://www.google.com/imghp',
    '- link "Maps" [ref=e2]:', '  - /url: https://maps.google.com/',
  ];
  const run = (url: string, lines: string[]) =>
    classifySnapshot({ board: 'Dork', url }, [`- Page URL: ${url}`, ...lines].join('\n'));

  it('English zero-hit SERP is empty', () => {
    const r = run(serpUrl, [...nav, '- text: Your search - site:jobs.lever.co engineer - did not match any documents.']);
    expect(r.outcome).toBe('empty');
  });

  it('German zero-hit SERP is empty', () => {
    const r = run(serpUrl, [...nav, '- text: Es wurden keine mit deiner Suchanfrage site:jobs.lever.co übereinstimmenden Dokumente gefunden.']);
    expect(r.outcome).toBe('empty');
  });

  it('consent interstitial is blocked as wall', () => {
    const r = run('https://consent.google.com/ml?continue=https://www.google.com/search', [
      '- heading: Before you continue to Google', `- text: ${'x'.repeat(250)}`,
    ]);
    expect(r.outcome).toBe('blocked');
    expect(r.blockKind).toBe('wall');
  });

  it('/sorry page is blocked', () => {
    const r = run('https://www.google.com/sorry/index?continue=https://www.google.com/search', [
      '- text: Our systems have detected unusual traffic', `- text: ${'x'.repeat(250)}`,
    ]);
    expect(r.outcome).toBe('blocked');
  });

  it('a real site: result still wins over a zero-hit phrase', () => {
    const r = run(serpUrl, [
      '- link "Engineer" [ref=e9]:', '  - /url: https://jobs.lever.co/acme/abc123',
      '- text: did not match any documents',
    ]);
    expect(r.outcome).toBe('searched');
  });
});

describe('isExplicitlyEmpty', () => {
  it('is exported and recognises German phrasing', () => {
    expect(isExplicitlyEmpty('Keine Stellen gefunden')).toBe(true);
    expect(isExplicitlyEmpty('10 jobs found')).toBe(false);
  });
});

/** Posting URLs tier 2 keeps for a board with `pattern`, given link lines. */
function patternUrls(url: string, pattern: string, links: Array<[string, string]>, pageUrl?: string): string[] {
  const lines = links.map(([title, href], i) => `- link "${title}" [ref=e${i}]: ${href}`);
  if (pageUrl) lines.unshift(`- Page URL: ${pageUrl}`);
  const result = classifySnapshot({ board: 'B', url, postingUrlPattern: pattern }, lines.join('\n'));
  return result.postings.filter((p) => p.ats === 'board-pattern').map((p) => p.url);
}

describe('classifySnapshot tier 2 generic guards', () => {
  it('rejects pagination segments under a wildcard-prefixed pattern', () => {
    const urls = patternUrls('https://acme.example/careers', 'https://acme.example/*jobs/*', [
      ['Next', 'https://acme.example/jobs/page/2'],
      ['Weiter', 'https://acme.example/en/jobs/seite-3'],
      ['Real', 'https://acme.example/jobs/senior-backend-engineer'],
    ]);
    expect(urls).toEqual(['https://acme.example/jobs/senior-backend-engineer']);
  });

  it('rejects an empty trailing wildcard', () => {
    const urls = patternUrls('https://acme.example/careers', 'https://acme.example/jobs/*', [
      ['Page two', 'https://acme.example/jobs/?page=2'],
      ['All jobs', 'https://acme.example/jobs/'],
      ['Real', 'https://acme.example/jobs/senior-backend-engineer'],
    ]);
    expect(urls).toEqual(['https://acme.example/jobs/senior-backend-engineer']);
  });

  it('keeps a link under a double-star tail pattern', () => {
    const urls = patternUrls('https://acme.example/careers', 'https://acme.example/jobs/**', [
      ['Real', 'https://acme.example/jobs/senior-engineer'],
    ]);
    expect(urls).toEqual(['https://acme.example/jobs/senior-engineer']);
  });

  it('keeps query-keyed postings and rejects an empty query value', () => {
    const urls = patternUrls('https://acme.example/careers', 'https://acme.example/job?id=*', [
      ['Real', 'https://acme.example/job?id=123'],
      ['Empty', 'https://acme.example/job?id='],
    ]);
    expect(urls).toEqual(['https://acme.example/job?id=123']);
  });

  it('rejects an empty tail after a wildcard-prefixed segment', () => {
    const urls = patternUrls('https://startupjobs.de/jobs', 'https://startupjobs.de/*jobs/*', [
      ['Index', 'https://startupjobs.de/en/jobs/'],
    ]);
    expect(urls).toEqual([]);
  });

  it('rejects links equal to the board URL or the snapshot page URL', () => {
    const urls = patternUrls('https://acme.example/jobs/all', 'https://acme.example/jobs/*', [
      ['Self board', 'https://acme.example/jobs/all#top'],
      ['Self page', 'https://acme.example/jobs/current'],
      ['Real', 'https://acme.example/jobs/other'],
    ], 'https://acme.example/jobs/current');
    expect(urls).toEqual(['https://acme.example/jobs/other']);
  });

  it('rejects numeric and letterless titles but keeps a short one', () => {
    const urls = patternUrls('https://acme.example/careers', 'https://acme.example/jobs/*', [
      ['2', 'https://acme.example/jobs/a1'],
      ['»', 'https://acme.example/jobs/b2'],
      ['CTO', 'https://acme.example/jobs/c3'],
    ]);
    expect(urls).toEqual(['https://acme.example/jobs/c3']);
  });

  it('handles the startupjobs.de and talentsift.de presets', () => {
    const startup = patternUrls('https://startupjobs.de/jobs', 'https://startupjobs.de/*jobs/*', [
      ['One', 'https://startupjobs.de/jobs/3f2a9c1e-uuid'],
      ['Two', 'https://startupjobs.de/en/jobs/3f2a9c1e-uuid'],
      ['Page', 'https://startupjobs.de/en/jobs/page/2'],
    ]);
    expect(startup).toEqual(['https://startupjobs.de/jobs/3f2a9c1e-uuid', 'https://startupjobs.de/en/jobs/3f2a9c1e-uuid']);
    const talent = patternUrls('https://talentsift.de/jobs', 'https://talentsift.de/jobs/*', [
      ['Dev', 'https://talentsift.de/jobs/senior-dev-berlin'],
      ['Page', 'https://talentsift.de/jobs/?page=2'],
    ]);
    expect(talent).toEqual(['https://talentsift.de/jobs/senior-dev-berlin']);
  });
});

describe('classifySnapshot link extraction', () => {
  const board = { board: 'Acme', url: 'https://acme.example/careers' };

  it('resolves a Playwright indented child /url: link with a relative href', () => {
    const snapshot = [
      '- Page URL: https://acme.example/careers',
      '- link "Senior Backend Engineer" [ref=e15] [cursor=pointer]:',
      '  - /url: /jobs/greenhouse-lookalike',
      '- link "Apply via Greenhouse" [ref=e16]:',
      '  - /url: https://boards.greenhouse.io/acme/jobs/12345',
    ].join('\n');
    const result = classifySnapshot(board, snapshot);
    expect(result.outcome).toBe('searched');
    expect(result.postings).toEqual([{ url: 'https://boards.greenhouse.io/acme/jobs/12345', title: 'Apply via Greenhouse', ats: 'greenhouse' }]);
  });

  it('still parses the same-line link format', () => {
    const snapshot = '- link "Lever posting" [ref=e3]: https://jobs.lever.co/acme/abc123';
    const result = classifySnapshot(board, snapshot);
    expect(result.outcome).toBe('searched');
    expect(result.postings[0].ats).toBe('lever');
  });

  it('ATS tier wins over the pattern tier even when both are present', () => {
    const boardWithPattern = { ...board, postingUrlPattern: 'https://acme.example/jobs/*' };
    const snapshot = [
      '- link "ATS posting" [ref=e1]: https://jobs.lever.co/acme/xyz',
      '- link "Board posting" [ref=e2]: https://acme.example/jobs/999',
    ].join('\n');
    const result = classifySnapshot(boardWithPattern, snapshot);
    expect(result.postings).toEqual([{ url: 'https://jobs.lever.co/acme/xyz', title: 'ATS posting', ats: 'lever' }]);
  });

  it('falls back to the board posting URL pattern tier when no ATS link matches', () => {
    const boardWithPattern = { ...board, postingUrlPattern: 'https://acme.example/jobs/*' };
    const snapshot = [
      '- link "Board posting one" [ref=e1]: https://acme.example/jobs/111',
      '- link "Unrelated nav link" [ref=e2]: https://acme.example/about',
    ].join('\n');
    const result = classifySnapshot(boardWithPattern, snapshot);
    expect(result.postings).toEqual([{ url: 'https://acme.example/jobs/111', title: 'Board posting one', ats: 'board-pattern' }]);
  });

  it('same-site rule extracts with ≥2 distinct qualifying job links', () => {
    const snapshot = [
      '- Page URL: https://acme.example/careers',
      '- link "Senior Backend Engineer" [ref=e1]: https://acme.example/jobs/senior-backend-engineer',
      '- link "Staff Data Scientist 4821" [ref=e2]: https://acme.example/jobs/staff-data-scientist-4821',
    ].join('\n');
    const result = classifySnapshot(board, snapshot);
    expect(result.outcome).toBe('searched');
    expect(result.postings).toHaveLength(2);
    expect(result.postings.every((p) => p.ats === 'board-heuristic')).toBe(true);
  });

  it('a single qualifying same-site link is not enough — needs_review', () => {
    const snapshot = [
      '- Page URL: https://acme.example/careers',
      '- link "Senior Backend Engineer" [ref=e1]: https://acme.example/jobs/senior-backend-engineer',
    ].join('\n');
    const result = classifySnapshot(board, snapshot);
    expect(result.outcome).toBe('needs_review');
  });

  it('nav/category-only links (no posting-shaped later segment) never qualify', () => {
    const snapshot = [
      '- Page URL: https://acme.example/careers',
      '- link "All Jobs" [ref=e1]: https://acme.example/jobs',
      '- link "Engineering" [ref=e2]: https://acme.example/jobs/engineering',
    ].join('\n');
    const result = classifySnapshot(board, snapshot);
    expect(result.outcome).toBe('needs_review');
  });

  it('an off-site link never qualifies for the same-site tier', () => {
    const snapshot = [
      '- Page URL: https://acme.example/careers',
      '- link "Senior Backend Engineer" [ref=e1]: https://acme.example/jobs/senior-backend-engineer',
      '- link "Other company posting" [ref=e2]: https://other.example/jobs/staff-data-scientist-4821',
    ].join('\n');
    const result = classifySnapshot(board, snapshot);
    expect(result.outcome).toBe('needs_review');
  });

  it('an earlier inline "- Page URL:" mention does not win over the real line', () => {
    const snapshot = [
      '- paragraph: See - Page URL: https://other.example/x for details',
      '- Page URL: https://acme.example/careers',
      '- link "Senior Backend Engineer" [ref=e1] [cursor=pointer]:',
      '  - /url: /jobs/senior-backend-engineer',
    ].join('\n');
    const result = classifySnapshot(board, snapshot);
    expect(result.postings).toEqual([]);
    expect(result.outcome).toBe('needs_review');
  });

  it('a board posting URL pattern does not match a differently-cased URL', () => {
    const boardWithPattern = { ...board, postingUrlPattern: 'https://acme.example/jobs/*' };
    const snapshot = '- link "Job posting" [ref=e1]: https://acme.example/JOBS/123';
    const result = classifySnapshot(boardWithPattern, snapshot);
    expect(result.postings.some((p) => p.ats === 'board-pattern')).toBe(false);
  });

  it('pagination links (page-2, page/3, seite-2) never qualify for the same-site tier', () => {
    const snapshot = [
      '- Page URL: https://acme.example/careers',
      '- link "Next page" [ref=e1]: https://acme.example/jobs/page-2',
      '- link "Previous page" [ref=e2]: https://acme.example/jobs/page-3',
      '- link "German pagination" [ref=e3]: https://acme.example/karriere/stellen/seite-2',
      '- link "Nested pagination" [ref=e4]: https://acme.example/jobs/page/4',
    ].join('\n');
    const result = classifySnapshot(board, snapshot);
    expect(result.outcome).toBe('needs_review');
  });
});
