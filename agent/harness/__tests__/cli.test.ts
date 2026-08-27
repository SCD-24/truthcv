import { describe, it, expect, vi } from 'vitest';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import type { McpClientPool, NamespacedTool } from '../mcp/client.js';
import type { HarnessEvent, ProviderAdapter, ToolCall } from '../providers/types.js';
import { ExitCode, runCli, type CliDeps } from '../cli.js';

/** A tool call referencing the fake pool's one allowed tool. */
const A_TOOL_CALL: ToolCall = { id: 'c1', name: 'truthcv__start_run', arguments: {} };

/**
 * A scripted {@link ProviderAdapter}: successive `sendMessage` calls yield
 * successive scripts; the last script repeats forever once they run out.
 */
function scriptedAdapter(scripts: HarnessEvent[][]): ProviderAdapter {
  let call = 0;
  return {
    async *sendMessage(_request) {
      const script = scripts[Math.min(call, scripts.length - 1)];
      call += 1;
      for (const event of script) yield event;
    },
  };
}

/** A fake MCP pool exposing one allowed truthcv tool; no network anywhere. */
function fakePool(tools?: NamespacedTool[]): McpClientPool {
  const list: NamespacedTool[] = tools ?? [
    { namespacedName: 'truthcv__start_run', serverName: 'truthcv', toolName: 'start_run', description: 'd', inputSchema: { type: 'object' } },
  ];
  return {
    callTool: vi.fn(async () => ({ content: 'ok', isError: false })),
    refreshTools: vi.fn(async () => {}),
    listTools: () => list,
  } as unknown as McpClientPool;
}

/** Capture stdout/stderr lines and supply a fake adapter + pool to the CLI. */
function harness(
  adapter: ProviderAdapter,
  pool: McpClientPool,
  overrides: Partial<CliDeps> = {},
): { deps: CliDeps; stdout: string[]; stderr: string[]; createAdapter: ReturnType<typeof vi.fn>; createPool: ReturnType<typeof vi.fn> } {
  const stdout: string[] = [];
  const stderr: string[] = [];
  const createAdapter = vi.fn(() => adapter);
  const createPool = vi.fn(async () => pool);
  const deps: CliDeps = {
    createAdapter,
    createPool,
    loadConfig: () => [{ name: 'truthcv', url: 'http://x' }],
    stdout: (line) => stdout.push(line),
    stderr: (line) => stderr.push(line),
    readStdin: async () => '',
    ...overrides,
  };
  return { deps, stdout, stderr, createAdapter, createPool };
}

/** Base flags for a valid run; individual tests append/override as needed. */
const BASE_ARGS = ['--model', 'm', '--provider', 'claude', '--wire', 'anthropic-messages', '--token', 'tok'];

const doneEnd: HarnessEvent = { type: 'done', stopReason: 'end', message: { role: 'assistant', content: 'all done' } };

function doneToolCalls(content: string): HarnessEvent {
  return { type: 'done', stopReason: 'toolCalls', message: { role: 'assistant', content, toolCalls: [A_TOOL_CALL] } };
}

describe('runCli success path', () => {
  it('streams well-formed JSONL and exits 0 on a clean end', async () => {
    const adapter = scriptedAdapter([
      [{ type: 'text', delta: 'thinking' }, { type: 'toolCall', toolCall: A_TOOL_CALL }, doneToolCalls('thinking')],
      [{ type: 'text', delta: 'all done' }, doneEnd],
    ]);
    const { deps, stdout } = harness(adapter, fakePool());

    const code = await runCli([...BASE_ARGS, 'apply to jobs'], {}, deps);

    expect(code).toBe(ExitCode.Success);
    const parsed = stdout.map((line) => JSON.parse(line) as { type: string });
    for (const line of stdout) expect(() => JSON.parse(line)).not.toThrow();
    expect(parsed.some((e) => e.type === 'turnStart')).toBe(true);
    expect(parsed.some((e) => e.type === 'toolResult')).toBe(true);
    const last = parsed[parsed.length - 1] as { type: string; exitCode: number };
    expect(last.type).toBe('done');
    expect(last.exitCode).toBe(ExitCode.Success);
  });

  it('writes the final assistant text to --output-file', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'cli-test-'));
    const outPath = join(dir, 'final.txt');
    try {
      const adapter = scriptedAdapter([[{ type: 'text', delta: 'all done' }, doneEnd]]);
      const { deps } = harness(adapter, fakePool(), { writeOutput: undefined });

      const code = await runCli([...BASE_ARGS, '--output-file', outPath, 'go'], {}, deps);

      expect(code).toBe(ExitCode.Success);
      expect(await readFile(outPath, 'utf8')).toBe('all done');
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });
});

describe('runCli exit codes', () => {
  it('exits with the turn-cap code when the loop reports turnCapReached', async () => {
    const adapter = scriptedAdapter([[doneToolCalls('')]]);
    const { deps } = harness(adapter, fakePool());

    const code = await runCli([...BASE_ARGS, '--max-turns', '2', 'go'], {}, deps);

    expect(code).toBe(ExitCode.TurnCapReached);
    expect(code).not.toBe(ExitCode.Success);
  });

  it('exits with the provider-error code on a non-retryable error', async () => {
    const adapter = scriptedAdapter([[{ type: 'error', message: 'Bad request: 400 invalid', retryable: false }]]);
    const { deps } = harness(adapter, fakePool());

    const code = await runCli([...BASE_ARGS, 'go'], {}, deps);

    expect(code).toBe(ExitCode.ProviderError);
  });

  it('exits with the MCP-failure code when no tools are available', async () => {
    const adapter = scriptedAdapter([[doneEnd]]);
    const { deps, createAdapter } = harness(adapter, fakePool([]));

    const code = await runCli([...BASE_ARGS, 'go'], {}, deps);

    expect(code).toBe(ExitCode.McpFailure);
    expect(createAdapter).not.toHaveBeenCalled();
  });
});

describe('runCli bad configuration', () => {
  it('reports missing model with the bad-config code and builds nothing', async () => {
    const adapter = scriptedAdapter([[doneEnd]]);
    const { deps, createAdapter, createPool, stderr } = harness(adapter, fakePool());
    // No --model flag and no AGENT_LLM_MODEL fallback in env.
    const args = ['--provider', 'claude', '--wire', 'anthropic-messages', '--token', 'tok', 'go'];

    const code = await runCli(args, {}, deps);

    expect(code).toBe(ExitCode.BadConfig);
    expect(createAdapter).not.toHaveBeenCalled();
    expect(createPool).not.toHaveBeenCalled();
    expect(stderr.join('\n')).toContain('model is required');
  });
});

/**
 * Drive one tool call whose MCP result is `result` through the CLI and return
 * the single emitted `toolResult` line. The first turn calls the tool, the
 * second ends the run.
 */
async function toolResultLine(result: { content: unknown; isError: boolean }): Promise<Record<string, unknown>> {
  const pool = fakePool();
  (pool.callTool as ReturnType<typeof vi.fn>).mockImplementation(async () => result);
  const adapter = scriptedAdapter([
    [{ type: 'toolCall', toolCall: A_TOOL_CALL }, doneToolCalls('')],
    [doneEnd],
  ]);
  const { deps, stdout } = harness(adapter, pool);

  await runCli([...BASE_ARGS, 'go'], {}, deps);

  const lines = stdout.map((line) => JSON.parse(line) as Record<string, unknown>);
  const results = lines.filter((e) => e.type === 'toolResult');
  expect(results).toHaveLength(1);
  return results[0];
}

describe('runCli tool result logging', () => {
  it('emits the error message, the call id and isError for a failed tool call', async () => {
    const line = await toolResultLine({ content: 'element not found: ref e42', isError: true });

    expect(line.isError).toBe(true);
    expect(line.content).toBe('element not found: ref e42');
    expect(line.toolCallId).toBe(A_TOOL_CALL.id);
    expect(line.namespacedName).toBe(A_TOOL_CALL.name);
  });

  it('emits the call id but NO content for a successful tool call', async () => {
    const line = await toolResultLine({ content: 'a very large page snapshot', isError: false });

    expect(line.isError).toBe(false);
    expect(line.toolCallId).toBe(A_TOOL_CALL.id);
    // Success content is deliberately dropped: snapshots run to tens of kB.
    expect('content' in line).toBe(false);
  });

  it('truncates over-long error content and marks the truncation', async () => {
    const line = await toolResultLine({ content: 'x'.repeat(9000), isError: true });

    const content = line.content as string;
    expect(content.startsWith('x'.repeat(2000))).toBe(true);
    expect(content).toContain('[truncated]');
    expect(content).not.toContain('x'.repeat(2001));
  });

  it.each([
    ['missing', undefined],
    ['empty', ''],
    ['non-string', { message: 'oops' }],
  ])('emits a valid line without throwing when error content is %s', async (_label, content) => {
    const line = await toolResultLine({ content, isError: true });

    expect(line.isError).toBe(true);
    expect(line.content).toBe('');
    expect(line.toolCallId).toBe(A_TOOL_CALL.id);
  });

  it('still resolves namespacedName from the tool-call id', async () => {
    const line = await toolResultLine({ content: 'ok', isError: false });

    expect(line.namespacedName).toBe('truthcv__start_run');
  });
});

describe('runCli token redaction', () => {
  it('never echoes the raw token even when an error message embeds it', async () => {
    const token = 'SUPERSECRET-TOKEN-123';
    // An upstream error whose message happens to contain the raw token.
    const adapter = scriptedAdapter([[{ type: 'error', message: `auth failed for key ${token}`, retryable: false }]]);
    const { deps, stdout, stderr } = harness(adapter, fakePool());

    const code = await runCli(
      ['--model', 'm', '--provider', 'claude', '--wire', 'anthropic-messages', '--token', token, 'go'],
      {},
      deps,
    );

    expect(code).toBe(ExitCode.ProviderError);
    const all = [...stdout, ...stderr].join('\n');
    expect(all).not.toContain(token);
    expect(all).toContain('<redacted>');
  });
});
