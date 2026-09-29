import { describe, it, expect, vi } from 'vitest';
import { ExitCode, resolveConfig, parseArgs } from '../../cli.js';
import { parsePipelineArgs, runPipelineCli } from '../pipelineCli.js';
import type { McpClientPool } from '../../mcp/client.js';

/** A fake pool exposing truthcv tools; records calls. */
function fakePool(handler: (tool: string, args: Record<string, unknown>) => { content: string; isError?: boolean }) {
  const calls: Array<[string, Record<string, unknown>]> = [];
  const names = ['start_run', 'finish_run', 'check_gmail_responses', 'get_approved_applications'];
  const pool = {
    listTools: () => names.map((n) => ({ namespacedName: `truthcv__${n}`, serverName: 'truthcv', toolName: n, description: '', inputSchema: {} })),
    callTool: vi.fn(async (name: string, args: Record<string, unknown>) => {
      const tool = name.replace('truthcv__', '');
      calls.push([tool, args]);
      return handler(tool, args);
    }),
  } as unknown as McpClientPool;
  return { pool, calls };
}

function deps(pool: McpClientPool) {
  const out: Record<string, string> = {};
  const stdout: string[] = [];
  const stderr: string[] = [];
  return {
    out, stdout, stderr,
    d: {
      createPool: async () => pool,
      loadConfig: () => [{ name: 'truthcv', url: 'http://x' }],
      readFileText: async (p: string) => out[p] ?? '',
      writeOutput: async (p: string, t: string) => { out[p] = t; },
      stdout: (l: string) => stdout.push(l),
      stderr: (l: string) => stderr.push(l),
    },
  };
}

describe('pipelineCli', () => {
  it('parses the subcommand and flags', () => {
    const a = parsePipelineArgs(['discover-screen', '--job-config', 'j.json', '--out', 'o.json']);
    expect(a.command).toBe('discover-screen');
    expect(a.flags).toMatchObject({ 'job-config': 'j.json', out: 'o.json' });
  });

  it('start runs start_run, gmail check and writes the approved queue', async () => {
    const { pool, calls } = fakePool((tool) => ({ content: tool === 'get_approved_applications' ? '[{"url":"u"}]' : '{}' }));
    const { d, out } = deps(pool);
    const code = await runPipelineCli(['start', '--run-id', 'r1', '--out', 'a.json'], {}, d);
    expect(code).toBe(ExitCode.Success);
    expect(calls.map((c) => c[0])).toEqual(['start_run', 'check_gmail_responses', 'get_approved_applications']);
    expect(out['a.json']).toBe('[{"url":"u"}]');
  });

  it('start without --run-id is a config error', async () => {
    const { pool } = fakePool(() => ({ content: '{}' }));
    expect(await runPipelineCli(['start'], {}, deps(pool).d)).toBe(ExitCode.BadConfig);
  });

  it('finish completes only when no issues, else fails with a reason', async () => {
    const ok = fakePool(() => ({ content: '{}' }));
    expect(await runPipelineCli(['finish', '--run-id', 'r'], {}, deps(ok.pool).d)).toBe(ExitCode.Success);
    expect(ok.calls[0][1]).toMatchObject({ status: 'completed' });
    const bad = fakePool(() => ({ content: '{}' }));
    await runPipelineCli(['finish', '--run-id', 'r', '--issues', 'session 2 rc=3'], {}, deps(bad.pool).d);
    expect(bad.calls[0][1]).toMatchObject({ status: 'failed', stopped_reason: 'session 2 rc=3' });
  });

  it('finish reports failed when the state file is not ok', async () => {
    const { pool, calls } = fakePool(() => ({ content: '{}' }));
    const { d, out } = deps(pool);
    out['s.json'] = JSON.stringify({ ok: false, errors: ['boom'] });
    await runPipelineCli(['finish', '--run-id', 'r', '--state-file', 's.json'], {}, d);
    expect(calls[0][1].status).toBe('failed');
    expect(String(calls[0][1].stopped_reason)).toContain('boom');
  });

  it('finish counts per-item failures without failing the run', async () => {
    const { pool, calls } = fakePool(() => ({ content: '{}' }));
    const { d, out } = deps(pool);
    const items = ['u1 [P]: ' + 'e'.repeat(300), 'u2 [P]: bad'];
    const apply = 'apply pass https://u3 rc=1: reason';
    out['s.json'] = JSON.stringify({ ok: true, errors: [], itemErrors: items });
    out['af.txt'] = `${apply}\n`;
    const code = await runPipelineCli(['finish', '--run-id', 'r', '--state-file', 's.json', '--apply-failures-file', 'af.txt'], {}, d);
    expect(code).toBe(ExitCode.Success);
    expect(calls[0][1]).toMatchObject({ status: 'completed', stopped_reason: '', items_failed: 3, item_errors: [...items, apply] });
  });

  it('finish redacts a configured secret from item_errors', async () => {
    const { pool, calls } = fakePool(() => ({ content: '{}' }));
    const { d, out } = deps(pool);
    out['s.json'] = JSON.stringify({ ok: true, errors: [], itemErrors: ['u1 [P]: leaked sekret-token-123 here'] });
    out['af.txt'] = 'apply pass u2 rc=1: key sekret-token-123\n';
    await runPipelineCli(['finish', '--run-id', 'r', '--state-file', 's.json', '--apply-failures-file', 'af.txt'], { AGENT_LLM_API_KEY: 'sekret-token-123' }, d);
    const sent = JSON.stringify(calls[0][1].item_errors);
    expect(sent).not.toContain('sekret-token-123');
    expect(sent).toContain('<redacted>');
  });

  it('finish redacts a longer token whole when it contains a shorter one', async () => {
    const { pool, calls } = fakePool(() => ({ content: '{}' }));
    const { d, out } = deps(pool);
    out['af.txt'] = 'apply pass u2 rc=1: key sk-prod-extra\n';
    const env = { AGENT_LLM_API_KEY: 'sk-prod', AGENT_SCREENING_API_KEY: 'sk-prod-extra' };
    await runPipelineCli(['finish', '--run-id', 'r', '--apply-failures-file', 'af.txt'], env, d);
    const sent = JSON.stringify(calls[0][1].item_errors);
    expect(sent).not.toContain('-extra');
    expect(sent).toContain('<redacted>');
  });

  it('finish with a not-ok state fails the run but still passes items_failed', async () => {
    const { pool, calls } = fakePool(() => ({ content: '{}' }));
    const { d, out } = deps(pool);
    out['s.json'] = JSON.stringify({ ok: false, errors: ['boom'], itemErrors: ['a', 'b'] });
    await runPipelineCli(['finish', '--run-id', 'r', '--state-file', 's.json'], {}, d);
    expect(calls[0][1]).toMatchObject({ status: 'failed', items_failed: 2, item_errors: ['a', 'b'] });
  });

  it('stage-prompt prints the apply prompt; unknown stage exits 5', async () => {
    const { pool } = fakePool(() => ({ content: '{}' }));
    const a = deps(pool);
    expect(await runPipelineCli(['stage-prompt', 'apply'], {}, a.d)).toBe(ExitCode.Success);
    expect(a.stdout[0].length).toBeGreaterThan(100);
    expect(await runPipelineCli(['stage-prompt', 'nope'], {}, deps(pool).d)).toBe(ExitCode.BadConfig);
  });

  it('exits 4 when MCP has no tools and 5 for an unknown command', async () => {
    const empty = { listTools: () => [] } as unknown as McpClientPool;
    expect(await runPipelineCli(['finish', '--run-id', 'r'], {}, deps(empty).d)).toBe(ExitCode.McpFailure);
    expect(await runPipelineCli(['bogus'], {}, deps(empty).d)).toBe(ExitCode.BadConfig);
  });
});

describe('cli --system-prompt-file', () => {
  it('reads the file into config.systemPrompt', async () => {
    const parsed = parseArgs(['--system-prompt-file', 'sp.md', '--finish-tool', 'finish_application', 'go']);
    const c = await resolveConfig(parsed, {}, { readFileText: async () => ' STATIC ', readStdin: async () => '' });
    expect(c.systemPrompt).toBe('STATIC');
    expect(c.finishToolName).toBe('finish_application');
  });
});
