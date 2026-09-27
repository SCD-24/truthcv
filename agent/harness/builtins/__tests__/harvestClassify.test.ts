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
