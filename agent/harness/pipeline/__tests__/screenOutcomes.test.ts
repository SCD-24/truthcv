import { describe, it, expect, vi } from 'vitest';
import { screenCandidates, type ScreenStageDeps } from '../screenStage.js';
import { classifyStored, pickOutcome } from '../outcomes.js';
import type { HarnessEvent, ProviderAdapter } from '../../providers/types.js';
import type { Candidate } from '../types.js';

/** Adapter replying by profile: the reply whose key appears in the request text. */
function keyedAdapter(replies: Record<string, unknown>, fallback: unknown): ProviderAdapter {
  return {
    async *sendMessage(req): AsyncGenerator<HarnessEvent, void, unknown> {
      const prompt = JSON.stringify(req.messages);
      const hit = Object.keys(replies).find((k) => prompt.includes(k));
      const text = JSON.stringify(hit ? replies[hit] : fallback);
      yield { type: 'text', delta: text };
      yield { type: 'done', stopReason: 'end', message: { role: 'assistant', content: text } };
    },
  };
}

const TEXT = 'Senior engineer role. '.repeat(30);
const extract = keyedAdapter({}, { role: 'Engineer', company: 'Acme' });
const cand = (n: number, profiles: string[]): Candidate => ({ url: `https://a.test/${n}`, title: 't', channel: 'dork', profiles, sources: [] });

/** Record mock echoing the sent verdict as a created record. */
const recordEcho = () => vi.fn(async (args: Record<string, unknown>) => ({
  content: JSON.stringify({ id: 'i', created: true, verdict: args.verdict, screening_blocker: args.screening_blocker ?? '' }),
}));

function deps(over: Partial<ScreenStageDeps>): ScreenStageDeps {
  return {
    runId: 'r', criteria: { P: 'CRIT-P', Q: 'CRIT-Q' }, fetch: async () => ({ text: TEXT }),
    extractAdapter: extract, screeningAdapter: keyedAdapter({}, { verdict: 'passed' }), record: recordEcho(), ...over,
  };
}

describe('screenCandidates outcomes', () => {
  it('maps a pass to for_review and a rejection to rejected', async () => {
    const res = await screenCandidates([cand(1, ['P'])], deps({}));
    expect(res.outcomes).toEqual([{ url: 'https://a.test/1', outcome: 'for_review', detail: 'P' }]);
    const rej = await screenCandidates([cand(2, ['P'])], deps({ screeningAdapter: keyedAdapter({}, { verdict: 'rejected', failing_criterion: 'x', reason: 'y' }) }));
    expect(rej.outcomes.map((o) => o.outcome)).toEqual(['rejected']);
  });

  it('maps fetch failure to failed with the same text as the error', async () => {
    const res = await screenCandidates([cand(1, ['P'])], deps({ fetch: async () => ({ failed: true, reason: 'timeout' }) as never }));
    expect(res.errors).toHaveLength(1);
    expect(res.outcomes).toEqual([{ url: 'https://a.test/1', outcome: 'failed', detail: res.errors[0] }]);
  });

  it('maps a thrown error with no record to failed', async () => {
    const res = await screenCandidates([cand(1, ['P'])], deps({ fetch: async () => { throw new Error('boom'); } }));
    expect(res.outcomes).toEqual([{ url: 'https://a.test/1', outcome: 'failed', detail: 'https://a.test/1: boom' }]);
    expect(res.errors).toEqual(['https://a.test/1: boom']);
  });

  it('maps a recorded blocker to blocked and a failed blocker save to failed', async () => {
    const unreadable = { fetch: async () => ({ unreadable: true as const, blocker: 'login_required' as const, reason: 'x' }) };
    const ok = await screenCandidates([cand(1, ['P'])], deps(unreadable));
    expect(ok.outcomes).toEqual([{ url: 'https://a.test/1', outcome: 'blocked', detail: 'login_required' }]);
    const bad = await screenCandidates([cand(1, ['P'])], deps({ ...unreadable, record: vi.fn(async () => ({ content: 'no', isError: true })) }));
    expect(bad.outcomes.map((o) => o.outcome)).toEqual(['failed']);
    expect(bad.outcomes[0].detail).toBe(bad.errors[0]);
  });

  it('maps created:false covered to previously_screened', async () => {
    const record = vi.fn(async () => ({ content: JSON.stringify({ id: 'i', created: false, profile: 'Other', verdict: 'passed', screening_blocker: '' }) }));
    const res = await screenCandidates([cand(1, ['P'])], deps({ record }));
    expect(res.outcomes).toEqual([{ url: 'https://a.test/1', outcome: 'previously_screened', detail: 'screened by another record during this run' }]);
  });

  it('classifies a blocker save that returns an existing record from that record', async () => {
    const unreadable = { fetch: async () => ({ unreadable: true as const, blocker: 'login_required' as const, reason: 'x' }) };
    const record = vi.fn(async () => ({ content: JSON.stringify({ id: 'i', created: false, profile: 'Other', verdict: 'passed', screening_blocker: '' }) }));
    const res = await screenCandidates([cand(1, ['P'])], deps({ ...unreadable, record }));
    expect(res.outcomes.map((o) => o.outcome)).toEqual(['previously_screened']);
  });

  it('parses created:false even when the key is unicode-escaped', async () => {
    const unreadable = { fetch: async () => ({ unreadable: true as const, blocker: 'login_required' as const, reason: 'x' }) };
    const content = '{"\\u0063reated":false,"profile":"Other","verdict":"passed","screening_blocker":""}';
    const record = vi.fn(async () => ({ content }));
    const res = await screenCandidates([cand(1, ['P'])], deps({ ...unreadable, record }));
    expect(res.outcomes.map((o) => o.outcome)).toEqual(['previously_screened']);
  });

  it('keeps an earlier rejected over failed when a later profile throws', async () => {
    const adapter = keyedAdapter({ 'CRIT-P': { verdict: 'rejected', failing_criterion: 'x', reason: 'y' } }, { verdict: 'passed' });
    const record = vi.fn(async (args: Record<string, unknown>) => {
      if (args.profile === 'Q') throw new Error('db down');
      return { content: JSON.stringify({ id: 'i', created: true, verdict: args.verdict, screening_blocker: '' }) };
    });
    const res = await screenCandidates([cand(1, ['P', 'Q'])], deps({ screeningAdapter: adapter, record }));
    expect(res.outcomes.map((o) => o.outcome)).toEqual(['rejected']);
    expect(res.errors).toHaveLength(1);
    expect(res.errors[0]).toContain('db down');
  });

  it('maps no profile with criteria to failed', async () => {
    const res = await screenCandidates([cand(1, ['Z'])], deps({}));
    expect(res.outcomes).toEqual([{ url: 'https://a.test/1', outcome: 'failed', detail: 'no criteria for profiles: Z' }]);
  });

  it('prefers a later actionable pass over an earlier rejection', async () => {
    const adapter = keyedAdapter({ 'CRIT-P': { verdict: 'rejected', failing_criterion: 'x', reason: 'y' } }, { verdict: 'passed' });
    const res = await screenCandidates([cand(1, ['P', 'Q'])], deps({ screeningAdapter: adapter }));
    expect(res.outcomes.map((o) => o.outcome)).toEqual(['for_review']);
  });
});

describe('outcome helpers', () => {
  it('names a non-actionable uncovered verdict as failed', () => {
    const c = classifyStored(JSON.stringify({ created: true, verdict: 'deferred', screening_blocker: '' }), 'P');
    expect(c.outcome).toBe('failed');
    expect(c.detail).toContain('deferred');
  });

  it('orders for_review > blocked > rejected', () => {
    const pick = pickOutcome([{ profile: 'A', outcome: 'rejected', detail: 'a' }, { profile: 'B', outcome: 'blocked', detail: 'b' }], '');
    expect(pick.outcome).toBe('blocked');
  });

  it('ranks failed above previously_screened', () => {
    const pick = pickOutcome([{ profile: 'A', outcome: 'previously_screened', detail: 'cov' }, { profile: 'B', outcome: 'failed', detail: 'boom' }], '');
    expect(pick.outcome).toBe('failed');
  });

  it('lists every profile outcome in the detail for 2+ profiles', () => {
    const pick = pickOutcome([{ profile: 'A', outcome: 'rejected', detail: 'rej' }, { profile: 'B', outcome: 'failed', detail: 'boom' }], '');
    expect(pick).toEqual({ outcome: 'rejected', detail: 'rej (A: rejected; B: failed)' });
  });

  it('leaves a single-profile detail unchanged', () => {
    const pick = pickOutcome([{ profile: 'A', outcome: 'rejected', detail: 'rej' }], '');
    expect(pick).toEqual({ outcome: 'rejected', detail: 'rej' });
  });
});
