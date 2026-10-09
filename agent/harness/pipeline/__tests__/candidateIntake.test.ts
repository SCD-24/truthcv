import { describe, expect, it, vi } from 'vitest';
import { createIntake } from '../candidateIntake.js';
import { CandidateQueue } from '../candidateQueue.js';
import { postingKey } from '../postingKey.js';
import type { Candidate } from '../types.js';

const SRC = [{ source: 'g', channel: 'dork' as const }];
const cand = (url: string, profiles: string[]): Candidate => ({ url, title: 'T', channel: 'dork', sources: SRC, profiles });

function setup() {
  const mcp = vi.fn(async (_t: string, a: Record<string, unknown>) => ({ content: JSON.stringify({ unscreened: a.urls, dropped: [] }), isError: false }));
  const queue = new CandidateQueue();
  return { mcp, queue, intake: createIntake(mcp, queue) };
}

describe('postingKey', () => {
  it('collapses linkedin subdomains and tracking params', () => {
    expect(postingKey('https://de.linkedin.com/jobs/view/123')).toBe(postingKey('https://www.linkedin.com/jobs/view/123/'));
    expect(postingKey('https://x.test/j/1/apply?utm_a=1&b=2&a=1#f')).toBe(postingKey('https://X.test/j/1?a=1&b=2'));
    expect(postingKey('not a url')).toBe('');
  });
});

describe('createIntake', () => {
  it('same posting under another profile later is not re-queued and not screened twice', async () => {
    const { intake, queue, mcp } = setup();
    await intake.push([cand('https://a.test/1', ['A'])]);
    await intake.push([cand('https://a.test/1', ['A', 'B'])]);
    queue.close();
    expect(await queue.take()).toMatchObject({ profiles: ['A'] });
    expect(await queue.take()).toBeUndefined();
    expect(mcp).toHaveBeenCalledTimes(1);
    expect(intake.dropped).toEqual([]);
    expect(intake.accepted).toMatchObject([{ url: 'https://a.test/1', profiles: ['A', 'B'] }]);
  });

  it('counts a regional linkedin variant in a later batch as a duplicate, fetched once', async () => {
    const { intake, queue, mcp } = setup();
    await intake.push([cand('https://www.linkedin.com/jobs/view/123', ['A'])]);
    await intake.push([cand('https://de.linkedin.com/jobs/view/123', ['A'])]);
    queue.close();
    expect(queue.size).toBe(1);
    expect(mcp).toHaveBeenCalledTimes(1);
    expect(intake.dropped).toEqual([{ url: 'https://de.linkedin.com/jobs/view/123', reason: 'duplicate', duplicate_of: 'https://www.linkedin.com/jobs/view/123', sources: SRC }]);
  });

  it('ignores an identical URL repeated for the same profile', async () => {
    const { intake, queue } = setup();
    await intake.push([cand('https://a.test/1', ['A']), cand('https://a.test/1', ['A'])]);
    await intake.push([cand('https://a.test/1', ['A'])]);
    expect(queue.size).toBe(1);
    expect(intake.dropped).toEqual([]);
  });
});
