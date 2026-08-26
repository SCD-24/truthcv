/**
 * End-to-end integration test proving the harness is genuinely
 * provider-agnostic and fails safely.
 *
 * Everything below runs fully in-process with NO real network, provider or MCP
 * call (per the repo's mock_external rule):
 *
 *   - The provider boundary is faked at the HTTP layer: `global.fetch` is
 *     stubbed to serve BOTH an Anthropic-Messages-shaped and an
 *     OpenAI-Chat-Completions-shaped response sequence, branching on the request
 *     URL. The REAL wire adapters are built through the REAL
 *     `createProviderAdapter`, so this exercises the two adapters end-to-end and
 *     proves they are equivalent from the OUTSIDE, not merely unit-equivalent.
 *
 *   - The MCP boundary is faked with a hand-written object satisfying the
 *     `McpClientPool` shape (listTools/callTool/reconnect/refreshTools) — fully
 *     offline, never touching the SDK transport — and can simulate a server that
 *     dies mid-run by returning `isError` from `callTool` after a point, exactly
 *     as the real pool's contract does for a failed call.
 *
 * The abstract per-turn scripts are rendered into each wire format from ONE
 * source, so identical model behaviour is driven through both adapters and the
 * resulting sequence of tool calls executed against the fake pool is asserted
 * to be equivalent — that equivalence is the actual point of the test.
 */

import { afterEach, describe, it, expect, vi } from 'vitest';

import type {
  McpClientPool,
  NamespacedTool,
  ToolCallResult,
} from '../mcp/client.js';
import type { ConversationMessage } from '../providers/types.js';
import { createProviderAdapter, type Wire } from '../providers/registry.js';
import { runLoop, type LoopConfig, type LoopResult } from '../loop.js';

/** An injected sleep that never actually waits, so tests run instantly. */
const noSleep = async (): Promise<void> => {};

/** The two wire formats under test, driven from one abstract script. */
const WIRES = ['anthropic-messages', 'openai-chat-completions'] as const;

/** Fake base URLs so the stubbed fetch can branch on the request URL. */
const ANTHROPIC_BASE = 'https://fake-anthropic.test';
const OPENAI_BASE = 'https://fake-openai.test';

/**
 * One scripted model turn, wire-independent. Rendered into each wire format so
 * the exact same behaviour drives both adapters.
 */
type TurnScript =
  | { type: 'toolCall'; id: string; name: string; args: Record<string, unknown> }
  | { type: 'end'; text: string }
  | { type: 'length'; id: string; name: string; args: Record<string, unknown>; text?: string };

/** Render an abstract turn into an Anthropic Messages response body. */
function renderAnthropic(turn: TurnScript): unknown {
  const usage = { input_tokens: 5, output_tokens: 5 };
  if (turn.type === 'end') {
    return { content: [{ type: 'text', text: turn.text }], stop_reason: 'end_turn', usage };
  }
  const toolUse = { type: 'tool_use', id: turn.id, name: turn.name, input: turn.args };
  if (turn.type === 'length') {
    const content = turn.text ? [{ type: 'text', text: turn.text }, toolUse] : [toolUse];
    return { content, stop_reason: 'max_tokens', usage };
  }
  return { content: [toolUse], stop_reason: 'tool_use', usage };
}

/** Render an abstract turn into an OpenAI Chat Completions response body. */
function renderOpenAi(turn: TurnScript): unknown {
  const usage = { prompt_tokens: 5, completion_tokens: 5 };
  if (turn.type === 'end') {
    return { choices: [{ message: { content: turn.text }, finish_reason: 'stop' }], usage };
  }
  const toolCalls = [
    { id: turn.id, type: 'function', function: { name: turn.name, arguments: JSON.stringify(turn.args) } },
  ];
  const finishReason = turn.type === 'length' ? 'length' : 'tool_calls';
  const content = turn.type === 'length' ? (turn.text ?? '') : null;
  return { choices: [{ message: { content, tool_calls: toolCalls }, finish_reason: finishReason }], usage };
}

/** A minimal Response-like object exposing only what the adapters read. */
function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response;
}

/**
 * Stub `global.fetch` to serve BOTH wire formats from independent queues,
 * branching on the request URL. Each wire's queue is seeded with the same
 * abstract turns so both adapters are driven identically.
 */
function installFetch(scripts: { anthropic?: TurnScript[]; openai?: TurnScript[] }): void {
  const anthropicQueue = [...(scripts.anthropic ?? [])];
  const openaiQueue = [...(scripts.openai ?? [])];
  const fetchMock = vi.fn(async (input: unknown): Promise<Response> => {
    const url = String(input);
    if (url.includes('/v1/messages')) {
      const turn = anthropicQueue.shift();
      if (!turn) throw new Error('anthropic fetch queue exhausted');
      return jsonResponse(renderAnthropic(turn));
    }
    if (url.includes('/chat/completions')) {
      const turn = openaiQueue.shift();
      if (!turn) throw new Error('openai fetch queue exhausted');
      return jsonResponse(renderOpenAi(turn));
    }
    throw new Error(`unexpected fetch to real network: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
}

/** Build the REAL adapter for a wire via the REAL registry, against fake bases. */
function makeAdapter(wire: Wire) {
  if (wire === 'anthropic-messages') {
    return createProviderAdapter({
      provider: 'claude',
      wire,
      model: 'claude-fake',
      token: 'fake-key',
      baseUrl: ANTHROPIC_BASE,
      authType: 'api_key',
    });
  }
  return createProviderAdapter({
    provider: 'openrouter',
    wire,
    model: 'fake-model',
    token: 'fake-key',
    baseUrl: OPENAI_BASE,
    authType: 'api_key',
  });
}

/** A tool call recorded by the fake pool, for equivalence comparison. */
interface RecordedCall {
  name: string;
  args: Record<string, unknown>;
}

/**
 * A hand-written fake satisfying the {@link McpClientPool} shape. Exposes two
 * allowed truthcv tools, records every executed call, and can simulate a server
 * that dies mid-run via `callBehavior` returning an `isError` result — matching
 * the real pool's contract of returning (not throwing) an error result.
 */
function fakePool(callBehavior?: (n: number, name: string, args: Record<string, unknown>) => ToolCallResult) {
  const calls: RecordedCall[] = [];
  let n = 0;
  const schema = { type: 'object', properties: {} } as Record<string, unknown>;
  const tools: NamespacedTool[] = [
    { namespacedName: 'truthcv__start_run', serverName: 'truthcv', toolName: 'start_run', description: 'start', inputSchema: schema },
    { namespacedName: 'truthcv__record_run_note', serverName: 'truthcv', toolName: 'record_run_note', description: 'note', inputSchema: schema },
  ];
  const callTool = vi.fn(async (name: string, args: Record<string, unknown>): Promise<ToolCallResult> => {
    n += 1;
    calls.push({ name, args });
    return callBehavior ? callBehavior(n, name, args) : { content: 'ok', isError: false };
  });
  const refreshTools = vi.fn(async () => {});
  const reconnect = vi.fn(async () => {});
  const listTools = vi.fn(() => tools);
  const pool = { callTool, refreshTools, reconnect, listTools } as unknown as McpClientPool;
  return { pool, calls, callTool };
}

/** Drive the real loop with the real adapter for `wire` and the given fake pool. */
function runFor(wire: Wire, pool: McpClientPool, config: LoopConfig): Promise<LoopResult> {
  const initialMessages: ConversationMessage[] = [{ role: 'user', content: 'apply to jobs' }];
  return runLoop({
    adapter: makeAdapter(wire),
    pool,
    systemPrompt: 'you are a job-application agent',
    initialMessages,
    config,
    sleep: noSleep,
  });
}

/** Seed a single wire's fetch queue from one abstract script. */
function installFor(wire: Wire, turns: TurnScript[]): void {
  installFetch(wire === 'anthropic-messages' ? { anthropic: turns } : { openai: turns });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('integration: provider-agnostic harness end-to-end', () => {
  it.each(WIRES)('completes the scripted 2-turn tool-calling exchange to a clean end (%s)', async (wire) => {
    const script: TurnScript[] = [
      { type: 'toolCall', id: 'c1', name: 'truthcv__start_run', args: { run_id: 'run-1' } },
      { type: 'end', text: 'all done' },
    ];
    installFor(wire, script);
    const { pool, callTool } = fakePool();

    const result = await runFor(wire, pool, { maxTurns: 5 });

    expect(result.stopReason).toBe('end');
    expect(result.turns).toBe(2);
    expect(callTool).toHaveBeenCalledTimes(1);
    expect(callTool).toHaveBeenCalledWith('truthcv__start_run', { run_id: 'run-1' });
  });

  it('executes an equivalent sequence of tool calls across both wire formats', async () => {
    // One abstract script; rendered into BOTH wires from a single source.
    const script: TurnScript[] = [
      { type: 'toolCall', id: 'c1', name: 'truthcv__start_run', args: { run_id: 'run-1' } },
      { type: 'toolCall', id: 'c2', name: 'truthcv__record_run_note', args: { note: 'progress', count: 2 } },
      { type: 'end', text: 'all done' },
    ];

    installFetch({ anthropic: script, openai: script });

    const anthropic = fakePool();
    const anthropicResult = await runFor('anthropic-messages', anthropic.pool, { maxTurns: 5 });

    const openai = fakePool();
    const openaiResult = await runFor('openai-chat-completions', openai.pool, { maxTurns: 5 });

    // Both wires reach the same clean terminal state...
    expect(anthropicResult.stopReason).toBe('end');
    expect(openaiResult.stopReason).toBe('end');
    expect(anthropicResult.turns).toBe(3);
    expect(openaiResult.turns).toBe(3);

    // ...and — the point of the test — the SEQUENCE of tool calls (name + args)
    // actually executed against the pool is equivalent between the two wires.
    const expectedSequence: RecordedCall[] = [
      { name: 'truthcv__start_run', args: { run_id: 'run-1' } },
      { name: 'truthcv__record_run_note', args: { note: 'progress', count: 2 } },
    ];
    expect(anthropic.calls).toEqual(expectedSequence);
    expect(openai.calls).toEqual(expectedSequence);
    expect(openai.calls).toEqual(anthropic.calls);
  });

  it.each(WIRES)('continues sanely when a tool dies mid-run, surfacing an isError result (%s)', async (wire) => {
    const script: TurnScript[] = [
      { type: 'toolCall', id: 'c1', name: 'truthcv__start_run', args: { run_id: 'run-1' } },
      { type: 'toolCall', id: 'c2', name: 'truthcv__record_run_note', args: { note: 'still going' } },
      { type: 'end', text: 'wrapped up' },
    ];
    installFor(wire, script);

    // The fake server "dies" on its second call: it returns an isError result
    // (matching the real pool contract) rather than throwing, so the loop is
    // exercised on the tool-failure path tools.ts already contracts for.
    const { pool, callTool } = fakePool((n) =>
      n === 1
        ? { content: 'ok', isError: false }
        : { content: "MCP server 'truthcv' died mid-run", isError: true },
    );

    const result = await runFor(wire, pool, { maxTurns: 5 });

    // The loop does not crash and produces a LoopResult that terminates cleanly.
    expect(result.stopReason).toBe('end');
    expect(result.turns).toBe(3);
    expect(callTool).toHaveBeenCalledTimes(2);

    // The failed call's isError result is fed back rather than taking down the run.
    const erroredResults = result.messages
      .flatMap((m) => m.toolResults ?? [])
      .filter((r) => r.isError === true);
    expect(erroredResults).toHaveLength(1);
    expect(erroredResults[0]?.content).toContain('died mid-run');
  });

  it.each(WIRES)('never executes a tool call recovered from a truncated response (%s)', async (wire) => {
    const script: TurnScript[] = [
      // Turn 1 is TRUNCATED (finish reason length/max_tokens) but carries a tool call.
      { type: 'length', id: 'c1', name: 'truthcv__start_run', args: { run_id: 'run-1' }, text: 'partial' },
      { type: 'end', text: 'recovered' },
    ];
    installFor(wire, script);
    const { pool, callTool } = fakePool();

    const result = await runFor(wire, pool, { maxTurns: 5 });

    // The tool call recovered from the truncated message is NEVER dispatched to
    // the pool (loop.ts's 'length' handling), and instead is failed back.
    expect(callTool).not.toHaveBeenCalled();
    const truncatedResult = result.messages
      .flatMap((m) => m.toolResults ?? [])
      .find((r) => r.isError === true);
    expect(truncatedResult?.content).toContain('truncated');
    // The loop still terminates on a real LoopResult.
    expect(result.stopReason).toBe('end');
  });
});
