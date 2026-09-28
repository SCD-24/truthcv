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

describe('isExplicitlyEmpty', () => {
  it('is exported and recognises German phrasing', () => {
    expect(isExplicitlyEmpty('Keine Stellen gefunden')).toBe(true);
    expect(isExplicitlyEmpty('10 jobs found')).toBe(false);
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
