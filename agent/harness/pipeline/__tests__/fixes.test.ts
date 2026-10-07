import { describe, it, expect, vi } from 'vitest';
import { composeStagePrompt } from '../stagePrompt.js';
import { screenCandidates } from '../screenStage.js';
import { discover, aggregateCoverage } from '../discover.js';
import { ExitCode } from '../../cli.js';
import { runPipelineCli } from '../pipelineCli.js';
import type { HarnessEvent, ProviderAdapter } from '../../providers/types.js';
import type { McpClientPool } from '../../mcp/client.js';
import type { BrowserToolCall } from '../../builtins/harvestTypes.js';
import type { Candidate } from '../types.js';

const REJECT = { verdict: 'rejected', failing_criterion: 'salary', reason: 'too low' };
const PASS = { verdict: 'passed' };

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

const extract: ProviderAdapter = keyedAdapter({}, { role: 'Engineer', company: 'Acme' });
const recordOk = () => vi.fn(async (args: Record<string, unknown>) => ({
  content: JSON.stringify({ id: 'i', created: true, verdict: args.verdict, screening_blocker: args.screening_blocker ?? '' }),
}));

describe('screenCandidates fixes', () => {
  it('serializes browser fetches so they never interleave', async () => {
    let inFlight = 0;
    let max = 0;
    const cands: Candidate[] = [1, 2, 3, 4].map((n) => ({ url: `https://a.test/${n}`, title: 't', channel: 'dork', sources: [], profiles: ['P'] }));
    await screenCandidates(cands, {
      runId: 'r', criteria: { P: 'CRIT-P' },
      fetch: async () => {
        inFlight++; max = Math.max(max, inFlight);
        await new Promise((r) => setTimeout(r, 5));
        inFlight--;
        return { text: 'posting text' };
      },
      extractAdapter: extract, screeningAdapter: keyedAdapter({}, REJECT), record: recordOk(), concurrency: 4,
    });
    expect(max).toBe(1);
  });

  it('records a blocker with a valid role and a hostname company, never "unknown"', async () => {
    const record = recordOk();
    const res = await screenCandidates([{ url: 'https://www.jobs.example.com/p/1', title: '', channel: 'dork', sources: [], profiles: ['P'] }], {
      runId: 'r', criteria: { P: 'c' }, fetch: async () => ({ unreadable: true, blocker: 'login_required', reason: 'x' }),
      extractAdapter: extract, screeningAdapter: keyedAdapter({}, PASS), record,
    });
    const args = record.mock.calls[0][0];
    expect(args).toMatchObject({ company: 'jobs.example.com', verdict: '', screening_blocker: 'login_required' });
    expect(String(args.role).toLowerCase()).not.toBe('unknown');
    expect(args.role).toBeTruthy();
    expect(res.blockers).toBe(1);
    expect(res.errors).toEqual([]);
  });

  const run = (record: ReturnType<typeof recordOk>, replies: Record<string, unknown>, extra: Partial<Parameters<typeof screenCandidates>[1]> = {}) =>
    screenCandidates([{ url: 'https://a.test/1', title: 'T', channel: 'dork', sources: [], profiles: ['A', 'B'] }], {
      runId: 'r', criteria: { A: 'CRIT-A', B: 'CRIT-B' }, fetch: async () => ({ text: 'posting text' }),
      extractAdapter: extract, screeningAdapter: keyedAdapter(replies, REJECT), record, ...extra,
    });
  const profilesOf = (record: ReturnType<typeof recordOk>) => record.mock.calls.map((c) => c[0].profile);

  it('(a) records A rejected then B passed as one actionable pass for B', async () => {
    const record = recordOk();
    const res = await run(record, { 'CRIT-A': REJECT, 'CRIT-B': PASS });
    expect(profilesOf(record)).toEqual(['A', 'B']);
    expect(res.passes.map((p) => p.profile)).toEqual(['B']);
  });

  it('(b) still screens B when the server downgrades A\'s pass to rejected', async () => {
    const record = vi.fn(async (args: Record<string, unknown>) => ({
      content: JSON.stringify({ id: 'i', created: true, profile: args.profile, verdict: args.profile === 'A' ? 'rejected' : args.verdict, screening_blocker: '' }),
    }));
    const res = await run(record as ReturnType<typeof recordOk>, { 'CRIT-A': PASS, 'CRIT-B': PASS });
    expect(profilesOf(record as ReturnType<typeof recordOk>)).toEqual(['A', 'B']);
    expect(res.passes.map((p) => p.profile)).toEqual(['B']);
  });

  it('(c) never screens B after an actionable pass for A', async () => {
    const record = recordOk();
    const res = await run(record, { 'CRIT-A': PASS, 'CRIT-B': PASS });
    expect(profilesOf(record)).toEqual(['A']);
    expect(res.passes.map((p) => p.profile)).toEqual(['A']);
  });

  it('(d) stops when the store returns created:false with an existing passed record', async () => {
    const record = vi.fn(async () => ({ content: JSON.stringify({ id: 'i', created: false, profile: '', verdict: 'passed', screening_blocker: '' }) }));
    const res = await run(record as unknown as ReturnType<typeof recordOk>, { 'CRIT-A': PASS, 'CRIT-B': PASS });
    expect(record).toHaveBeenCalledTimes(1);
    expect(res.passes).toEqual([]);
  });

  it('(d2) does not treat a same-profile rejected created:false record as covered despite padding/case', async () => {
    const record = vi.fn(async () => ({ content: JSON.stringify({ id: 'i', created: false, profile: 'backend', verdict: 'rejected', screening_blocker: '' }) }));
    const res = await screenCandidates([{ url: 'https://a.test/1', title: 'T', channel: 'dork', sources: [], profiles: [' Backend ', 'B'] }], {
      runId: 'r', criteria: { ' Backend ': 'CRIT-A', B: 'CRIT-B' }, fetch: async () => ({ text: 'posting text' }),
      extractAdapter: extract, screeningAdapter: keyedAdapter({}, REJECT), record: record as unknown as ReturnType<typeof recordOk>,
    });
    expect(record).toHaveBeenCalledTimes(2);
    expect(res.passes).toEqual([]);
  });

  it('(e) still screens B after an error on A', async () => {
    const record = vi.fn(async (args: Record<string, unknown>) => (args.profile === 'A'
      ? { content: 'boom', isError: true }
      : { content: JSON.stringify({ id: 'i', created: true, profile: 'B', verdict: 'passed', screening_blocker: '' }) }));
    const res = await run(record as unknown as ReturnType<typeof recordOk>, { 'CRIT-A': PASS, 'CRIT-B': PASS });
    expect(record).toHaveBeenCalledTimes(2);
    expect(res.errors[0]).toContain('[A]');
    expect(res.passes.map((p) => p.profile)).toEqual(['B']);
  });
});

const GOOD = '- Page URL: https://x.test\n' + [1, 2].map((n) => `- link "Job ${n}" [ref=e${n}]: https://boards.greenhouse.io/acme/jobs/${n}`).join('\n');
function browser(snapshots: Record<string, string>): BrowserToolCall {
  let current = '';
  return async (tool, args) => {
    if (tool === 'browser_navigate') { current = String(args.url); return { content: 'ok', isError: false }; }
    if (tool === 'browser_snapshot') return { content: snapshots[current] ?? '', isError: false };
    return { content: 'ok', isError: false };
  };
}
const okMcp = () => vi.fn(async (_t: string, _a: Record<string, unknown>) => ({ content: '{"recorded":true}', isError: false }));
const covCalls = (m: ReturnType<typeof okMcp>) => m.mock.calls.filter((c) => c[0] === 'record_discovery_coverage').map((c) => c[1]);

describe('discover fixes', () => {
  it('gives profile-less feed postings every enabled profile', async () => {
    const out = await discover({
      profiles: [{ name: 'A', enabled: true }, { name: 'B', enabled: false }, { name: 'C', enabled: true }],
      feedPostings: [{ url: 'https://feed.test/1', title: 'F', source: 'rr' }],
    }, 'r', browser({}), okMcp());
    expect(out.candidates[0].profiles).toEqual(['A', 'C']);
  });

  it('records a failed feed channel and reports an error when feedError has no postings', async () => {
    const mcp = okMcp();
    const out = await discover({ feedError: 'HTTP 500' }, 'r', browser({}), mcp);
    expect(covCalls(mcp)).toContainEqual(expect.objectContaining({ channel: 'feed', status: 'extraction_failed', reason: 'HTTP 500' }));
    expect(out.errors.join(' ')).toContain('HTTP 500');
    expect(out.coverageComplete).toBe(false);
  });

  it('orders candidates feed -> direct -> dork', async () => {
    const call = browser({
      'https://board.test/jobs': '- Page URL: https://board.test/jobs\n' + [1, 2].map((n) => `- link "D ${n}" [ref=e${n}]: https://boards.greenhouse.io/direct/jobs/${n}`).join('\n'),
      'https://www.google.com/search?q=q': GOOD,
    });
    const out = await discover({
      feedPostings: [{ url: 'https://feed.test/1', source: 'rr', profile: 'A' }],
      directBoards: [{ url: 'https://board.test/jobs', profiles: [{ profile: 'A', keywords: ['dev'] }] }],
      searchQueries: [{ profiles: ['A'], source: 'g', query: 'q', url: 'https://www.google.com/search?q=q' }],
    }, 'r', call, okMcp());
    expect(out.candidates.map((c) => c.channel)).toEqual(['feed', ...out.candidates.slice(1).map((c) => c.channel)]);
    const channels = out.candidates.map((c) => c.channel);
    expect(channels.indexOf('feed')).toBeLessThan(channels.indexOf('direct'));
    expect(channels.indexOf('direct')).toBeLessThan(channels.indexOf('dork'));
  });

  it('searches a shared direct board per profile but records one coverage', async () => {
    const navigated: string[] = [];
    const typed: string[] = [];
    const inner = browser({});
    const call: BrowserToolCall = async (tool, args) => {
      if (tool === 'browser_navigate') navigated.push(String(args.url));
      if (JSON.stringify(args).includes('kwA') || JSON.stringify(args).includes('kwB')) typed.push(JSON.stringify(args));
      return inner(tool, args);
    };
    const mcp = okMcp();
    await discover({
      directBoards: [{ url: 'https://board.test/jobs', searchUrl: 'https://board.test/s?q={keywords}', profiles: [
        { profile: 'A', keywords: ['kwA'] }, { profile: 'B', keywords: ['kwB'] },
      ] }],
    }, 'r', call, mcp);
    expect(covCalls(mcp).filter((c) => c.channel === 'direct')).toHaveLength(1);
    const seen = [...navigated, ...typed].join(' ');
    expect(seen).toContain('kwA');
    expect(seen).toContain('kwB');
  });

  it('aggregates coverage: searched wins, else the worst status', () => {
    const c = (status: string, found = 0) => ({ status, reason: '', tier: '', found });
    expect(aggregateCoverage([c('blocked'), c('searched', 2)]).status).toBe('searched');
    expect(aggregateCoverage([c('empty'), c('blocked'), c('extraction_failed')]).status).toBe('blocked');
  });
});

function fakePool(handler: (tool: string) => string) {
  const calls: Array<[string, Record<string, unknown>]> = [];
  const names = ['start_run', 'finish_run', 'check_gmail_responses', 'get_approved_applications'];
  const pool = {
    listTools: () => names.map((n) => ({ namespacedName: `truthcv__${n}`, serverName: 'truthcv', toolName: n, description: '', inputSchema: {} })),
    callTool: vi.fn(async (name: string, args: Record<string, unknown>) => {
      const tool = name.replace('truthcv__', '');
      calls.push([tool, args]);
      return { content: handler(tool), isError: false };
    }),
  } as unknown as McpClientPool;
  const d = {
    createPool: async () => pool, loadConfig: () => [{ name: 'truthcv', url: 'http://x' }],
    readFileText: async () => '', writeOutput: async () => undefined, stdout: () => undefined, stderr: () => undefined,
  };
  return { calls, d };
}

describe('pipelineCli fixes', () => {
  it('leases approved applications to the run and passes the cap', async () => {
    const { calls, d } = fakePool(() => '[]');
    await runPipelineCli(['start', '--run-id', 'r1', '--out', 'a.json', '--limit', '3'], {}, d);
    expect(calls.find((c) => c[0] === 'get_approved_applications')![1]).toEqual({ run_id: 'r1', limit: 3 });
    const none = fakePool(() => '[]');
    await runPipelineCli(['start', '--run-id', 'r1', '--out', 'a.json'], {}, none.d);
    expect(none.calls.find((c) => c[0] === 'get_approved_applications')![1]).toEqual({ run_id: 'r1' });
  });

  it('treats {"recorded": false} as failure for start and finish', async () => {
    const start = fakePool((t) => (t === 'start_run' ? '{"recorded":false}' : '[]'));
    expect(await runPipelineCli(['start', '--run-id', 'r', '--out', 'a.json'], {}, start.d)).toBe(ExitCode.ProviderError);
    const fin = fakePool(() => '{"recorded":false}');
    expect(await runPipelineCli(['finish', '--run-id', 'r'], {}, fin.d)).toBe(ExitCode.ProviderError);
  });
});

describe('apply stage prompt', () => {
  it('ends with finish_application, has no run-identity section and carries the blocked_reason rule', async () => {
    const text = await composeStagePrompt('apply');
    expect(text).toContain('finish_application');
    expect(text).toContain('blocked_reason');
    expect(text).not.toContain('Your run id for this run is given');
    expect(text).not.toContain('call `finish_run` with it before you exit');
  });
});
