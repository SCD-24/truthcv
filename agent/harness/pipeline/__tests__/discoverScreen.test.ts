import { describe, it, expect, vi } from 'vitest';
import { ExitCode } from '../../cli.js';
import { runPipelineCli } from '../pipelineCli.js';
import type { HarnessEvent, ProviderAdapter } from '../../providers/types.js';
import type { McpClientPool } from '../../mcp/client.js';

const discoverMock = vi.hoisted(() => vi.fn());
vi.mock('../discover.js', () => ({ discover: discoverMock }));
vi.mock('../fetchPosting.js', () => ({ fetchPosting: async () => ({ text: 'posting text' }) }));

const adapter: ProviderAdapter = {
  async *sendMessage(): AsyncGenerator<HarnessEvent, void, unknown> {
    const text = JSON.stringify({ role: 'R', company: 'Co', verdict: 'passed' });
    yield { type: 'text', delta: text };
    yield { type: 'done', stopReason: 'end', message: { role: 'assistant', content: text } };
  },
};

const LONG = 'x'.repeat(500);

const SRC = [{ source: 'g', channel: 'dork' }];

function setup(found: { errors: string[]; coverageComplete: boolean }, funnelReply = '{"recorded":true,"mismatches":[],"truncated":false}') {
  const cand = { url: 'https://a.test/1', title: 'T', channel: 'dork', sources: SRC, profiles: ['P'] };
  discoverMock.mockResolvedValue({ candidates: [cand], allCandidates: [cand], dropped: [], ...found });
  const names = ['record_screening', 'record_source_funnel'];
  const pool = {
    listTools: () => names.map((n) => ({ namespacedName: `truthcv__${n}`, serverName: 'truthcv', toolName: n, description: '', inputSchema: {} })),
    callTool: vi.fn(async (name: string) => (name.endsWith('record_source_funnel') ? { content: funnelReply, isError: false } : { content: LONG, isError: true })),
  } as unknown as McpClientPool;
  const out: Record<string, string> = {
    'j.json': '{}', 'c.json': JSON.stringify({ P: 'crit' }),
  };
  const d = {
    createPool: async () => pool, loadConfig: () => [{ name: 'truthcv', url: 'http://x' }],
    createAdapter: () => adapter,
    readFileText: async (p: string) => out[p] ?? '',
    writeOutput: async (p: string, t: string) => { out[p] = t; },
    stdout: () => undefined, stderr: () => undefined,
  };
  return { d, out, pool };
}

const ENV = { AGENT_LLM_PROVIDER: 'ollama', AGENT_LLM_WIRE: 'openai-chat-completions', AGENT_LLM_MODEL: 'm', AGENT_LLM_BASE_URL: 'http://x', AGENT_LLM_API_KEY: 'k' };
const ARGS = ['discover-screen', '--run-id', 'r', '--job-config', 'j.json', '--criteria', 'c.json', '--out', 'o.json'];

describe('discover-screen per-item errors', () => {
  it('a record_screening error is per-item: exit 0, ok true, full itemErrors', async () => {
    const { d, out } = setup({ errors: [], coverageComplete: true });
    expect(await runPipelineCli(ARGS, ENV, d)).toBe(ExitCode.Success);
    const s = JSON.parse(out['o.json']) as { ok: boolean; errors: string[]; itemErrors: string[] };
    expect(s.ok).toBe(true);
    expect(s.errors).toEqual([]);
    expect(s.itemErrors).toHaveLength(1);
    expect(s.itemErrors[0].startsWith('https://a.test/1 [P]: ')).toBe(true);
    expect(s.itemErrors[0]).toContain(LONG);
  });

  it('records the funnel and flags the run on mismatches but not on truncation', async () => {
    const { d, out, pool } = setup({ errors: [], coverageComplete: true }, '{"recorded":true,"mismatches":["g: sum"],"truncated":false}');
    expect(await runPipelineCli(ARGS, ENV, d)).toBe(ExitCode.ProviderError);
    expect((JSON.parse(out['o.json']) as { errors: string[] }).errors).toEqual(['source funnel mismatch: g: sum']);
    const call = (pool.callTool as ReturnType<typeof vi.fn>).mock.calls.find((c) => String(c[0]).endsWith('record_source_funnel'))!;
    expect(call[1]).toMatchObject({ run_id: 'r', totals: { postings_seen: 1, failed: 1 }, urls: [{ url: 'https://a.test/1', outcome: 'failed' }] });
    const t = setup({ errors: [], coverageComplete: true }, '{"recorded":true,"mismatches":[],"truncated":true}');
    expect(await runPipelineCli(ARGS, ENV, t.d)).toBe(ExitCode.Success);
  });

  it('a discovery error is systemic: exit 3, ok false', async () => {
    const { d, out } = setup({ errors: ['discovery boom'], coverageComplete: true });
    expect(await runPipelineCli(ARGS, ENV, d)).toBe(ExitCode.ProviderError);
    const s = JSON.parse(out['o.json']) as { ok: boolean; errors: string[] };
    expect(s.ok).toBe(false);
    expect(s.errors).toEqual(['discovery boom']);
  });
});
