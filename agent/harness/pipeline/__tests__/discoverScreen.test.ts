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

function setup(found: { errors: string[]; coverageComplete: boolean }) {
  discoverMock.mockResolvedValue({
    candidates: [{ url: 'https://a.test/1', title: 'T', channel: 'dork', profiles: ['P'] }], ...found,
  });
  const names = ['record_screening'];
  const pool = {
    listTools: () => names.map((n) => ({ namespacedName: `truthcv__${n}`, serverName: 'truthcv', toolName: n, description: '', inputSchema: {} })),
    callTool: vi.fn(async () => ({ content: LONG, isError: true })),
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
  return { d, out };
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

  it('a discovery error is systemic: exit 3, ok false', async () => {
    const { d, out } = setup({ errors: ['discovery boom'], coverageComplete: true });
    expect(await runPipelineCli(ARGS, ENV, d)).toBe(ExitCode.ProviderError);
    const s = JSON.parse(out['o.json']) as { ok: boolean; errors: string[] };
    expect(s.ok).toBe(false);
    expect(s.errors).toEqual(['discovery boom']);
  });
});
