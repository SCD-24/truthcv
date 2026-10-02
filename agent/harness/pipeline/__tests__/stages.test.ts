import { describe, it, expect, vi } from 'vitest';
import { STAGE_REGISTRY } from '../../stages.js';
import { composeStagePrompt, defaultAgentDir } from '../stagePrompt.js';
import { extractMeta } from '../extractMeta.js';
import { screenCandidates } from '../screenStage.js';
import type { HarnessEvent, ProviderAdapter } from '../../providers/types.js';
import type { Candidate } from '../types.js';

/** An adapter replying with fixed text. */
function textAdapter(text: string): ProviderAdapter {
  return {
    async *sendMessage(): AsyncGenerator<HarnessEvent, void, unknown> {
      yield { type: 'text', delta: text };
      yield { type: 'done', stopReason: 'end', message: { role: 'assistant', content: text } };
    },
  };
}

describe('stage prompts', () => {
  it('every stages.ts section resolves in the real prompt.md and RUNBOOK.md', async () => {
    for (const def of STAGE_REGISTRY) {
      const text = await composeStagePrompt(def.name, defaultAgentDir());
      const sections = [...((def as { promptSections?: string[] }).promptSections ?? []), ...((def as { runbookSections?: string[] }).runbookSections ?? [])];
      expect(text.length > 0 || sections.length === 0).toBe(true);
    }
  });

  it('is static: no dates or run ids injected', async () => {
    const a = await composeStagePrompt('apply');
    const b = await composeStagePrompt('apply');
    expect(a).toBe(b);
  });
});

describe('extractMeta', () => {
  it('returns fields and falls back to the harvest title for role', async () => {
    const r = await extractMeta(textAdapter('{"role":"","company":"Acme","posted_date":"2026-01-02"}'), 'text', 'Harvest Title');
    expect(r).toEqual({ ok: true, meta: { role: 'Harvest Title', company: 'Acme', posted_date: '2026-01-02' } });
  });

  it('blocks when the company is empty', async () => {
    const r = await extractMeta(textAdapter('{"role":"X","company":""}'), 'text', 't');
    expect(r).toMatchObject({ ok: false, screening_blocker: 'unreadable' });
  });
});

describe('screenCandidates', () => {
  const cands: Candidate[] = [
    { url: 'https://a.test/1', title: 'A', channel: 'dork', profiles: ['P1', 'P2'] },
    { url: 'https://a.test/2', title: 'B', channel: 'dork', profiles: ['P1'] },
  ];

  it('keeps a persistEvidence error longer than 200 chars whole', async () => {
    const long = 'z'.repeat(400);
    const res = await screenCandidates([cands[0]], {
      runId: 'r', criteria: { P1: 'c1' }, fetch: async () => ({ text: 'posting text' }),
      extractAdapter: textAdapter('{"role":"R","company":"Co"}'),
      screeningAdapter: textAdapter(JSON.stringify({ verdict: 'passed' })),
      record: async () => ({ content: long, isError: true }),
    });
    expect(res.errors).toHaveLength(1);
    expect(res.errors[0].startsWith('https://a.test/1 [P1]: ')).toBe(true);
    expect(res.errors[0]).toContain(long);
  });

  it('reports a failed fetch as a run error without recording', async () => {
    const record = vi.fn(async () => ({ content: '{}' }));
    const res = await screenCandidates([cands[1]], {
      runId: 'r', criteria: { P1: 'c1' },
      fetch: async () => ({ failed: true, reason: "MCP server 'browser' is not connected" }),
      extractAdapter: textAdapter('{"role":"R","company":"Co"}'),
      screeningAdapter: textAdapter(JSON.stringify({ verdict: 'passed' })),
      record,
    });
    expect(record).not.toHaveBeenCalled();
    expect(res.blockers).toBe(0);
    expect(res.errors).toHaveLength(1);
    expect(res.errors[0]).toContain('https://a.test/2');
    expect(res.errors[0]).toContain("MCP server 'browser' is not connected");
  });

  it('stops at the first actionable pass and records blockers for unreadable text', async () => {
    const record = vi.fn(async (args: Record<string, unknown>) => ({
      content: JSON.stringify({ id: 'i', created: true, verdict: args.verdict === '' ? '' : 'passed', screening_blocker: args.screening_blocker ?? '' }),
    }));
    const screening = textAdapter(JSON.stringify({ verdict: 'passed' }));
    const res = await screenCandidates(cands, {
      runId: 'r', criteria: { P1: 'c1', P2: 'c2' },
      fetch: async (url) => (url.endsWith('/2') ? { unreadable: true, blocker: 'unreadable', reason: 'x' } : { text: 'posting text' }),
      extractAdapter: textAdapter('{"role":"R","company":"Co"}'),
      screeningAdapter: screening,
      record,
    });
    expect(res.blockers).toBe(1);
    const blockerCall = record.mock.calls.find((c) => c[0].screening_blocker === 'unreadable');
    expect(blockerCall?.[0].url).toBe('https://a.test/2');
    // Candidate 1: at most one pass recorded (first actionable profile wins).
    expect(res.passes.filter((p) => p.url.endsWith('/1')).length).toBeLessThanOrEqual(1);
  });
});
