import { describe, it, expect, vi } from 'vitest';

import type { McpClientPool, NamespacedTool } from '../mcp/client.js';
import type { ConversationMessage, HarnessEvent, ProviderAdapter, ToolCall } from '../providers/types.js';
import { backoffDelay, classifyError, isRetryable, runLoop } from '../loop.js';

/** An injected sleep that never actually waits, so tests run instantly. */
const noSleep = async (): Promise<void> => {};

/**
 * A scripted {@link ProviderAdapter}: successive calls yield successive scripts;
 * once the scripts run out the LAST one repeats forever (so "always toolCalls"
 * and "always error" adapters are easy to express). `calls()` reports how many
 * times a response was consumed.
 */
function scriptedAdapter(scripts: HarnessEvent[][]): { adapter: ProviderAdapter; calls: () => number } {
  let callCount = 0;
  const adapter: ProviderAdapter = {
    async *sendMessage(_request) {
      const script = scripts[Math.min(callCount, scripts.length - 1)];
      callCount += 1;
      for (const event of script) yield event;
    },
  };
  return { adapter, calls: () => callCount };
}

/** A fake MCP pool exposing one allowed truthcv tool; no network anywhere. */
function fakePool() {
  const callTool = vi.fn(async () => ({ content: 'ok', isError: false }));
  const refreshTools = vi.fn(async () => {});
  const tools: NamespacedTool[] = [
    { namespacedName: 'truthcv__start_run', serverName: 'truthcv', toolName: 'start_run', description: 'd', inputSchema: { type: 'object' } },
  ];
  const listTools = () => tools;
  const pool = { callTool, refreshTools, listTools } as unknown as McpClientPool;
  return { pool, callTool, refreshTools };
}

/** A tool call referencing the pool's one allowed tool. */
const A_TOOL_CALL: ToolCall = { id: 'c1', name: 'truthcv__start_run', arguments: {} };

const doneEnd: HarnessEvent = { type: 'done', stopReason: 'end', message: { role: 'assistant', content: 'all done' } };

function doneToolCalls(): HarnessEvent {
  return { type: 'done', stopReason: 'toolCalls', message: { role: 'assistant', content: '', toolCalls: [A_TOOL_CALL] } };
}

function doneLengthWithToolCall(): HarnessEvent {
  return { type: 'done', stopReason: 'length', message: { role: 'assistant', content: 'truncat', toolCalls: [A_TOOL_CALL] } };
}

const retryableError: HarnessEvent = { type: 'error', message: 'Service temporarily unavailable', retryable: true };
const fatalError: HarnessEvent = { type: 'error', message: 'Bad request: 400 invalid', retryable: false };
const malformedError: HarnessEvent = { type: 'error', message: 'Malformed tool call arguments', retryable: false };

/** Common runLoop wiring for a given adapter, pool and config. */
function run(adapter: ProviderAdapter, pool: McpClientPool, config: Parameters<typeof runLoop>[0]['config']) {
  const initialMessages: ConversationMessage[] = [{ role: 'user', content: 'apply to jobs' }];
  return runLoop({ adapter, pool, systemPrompt: 'you are an agent', initialMessages, config, sleep: noSleep });
}

describe('classifyError / isRetryable', () => {
  it('buckets retryable errors and marks them retryable', () => {
    expect(classifyError({ type: 'error', message: 'HTTP 429 rate limit', retryable: true })).toBe('rate-limit');
    expect(classifyError({ type: 'error', message: 'connection timeout', retryable: true })).toBe('timeout');
    expect(classifyError({ type: 'error', message: 'upstream boom', retryable: true })).toBe('service-unavailable');
    expect(isRetryable('rate-limit')).toBe(true);
    expect(isRetryable('service-unavailable')).toBe(true);
  });

  it('buckets fatal errors and marks them non-retryable', () => {
    expect(classifyError({ type: 'error', message: 'invalid auth 401', retryable: false })).toBe('authentication');
    expect(classifyError({ type: 'error', message: 'context length exceeded', retryable: false })).toBe('context-window-exceeded');
    expect(classifyError({ type: 'error', message: 'monthly usage limit hit', retryable: false })).toBe('usage-limit');
    expect(classifyError({ type: 'error', message: 'something else', retryable: false })).toBe('bad-request');
    expect(isRetryable('authentication')).toBe(false);
    expect(isRetryable('bad-request')).toBe(false);
  });

  it('caps backoff at maxRetryDelayMs', () => {
    expect(backoffDelay(20, 5_000)).toBe(5_000);
  });
});

describe('runLoop', () => {
  it('stops after one turn on an immediate end with no tool calls', async () => {
    const { adapter, calls } = scriptedAdapter([[doneEnd]]);
    const { pool, callTool } = fakePool();

    const result = await run(adapter, pool, { maxTurns: 5 });

    expect(result.stopReason).toBe('end');
    expect(result.turns).toBe(1);
    expect(calls()).toBe(1);
    expect(callTool).not.toHaveBeenCalled();
  });

  it('stops at exactly the hard turn cap when the model keeps calling tools', async () => {
    const { adapter } = scriptedAdapter([[doneToolCalls()]]);
    const { pool, callTool } = fakePool();

    const result = await run(adapter, pool, { maxTurns: 3 });

    expect(result.stopReason).toBe('turnCapReached');
    expect(result.stopReason).not.toBe('end');
    expect(result.turns).toBe(3);
    expect(callTool).toHaveBeenCalledTimes(3);
  });

  it('never executes a tool call recovered from a truncated (length) response', async () => {
    const { adapter } = scriptedAdapter([[doneLengthWithToolCall()], [doneEnd]]);
    const { pool, callTool } = fakePool();

    const result = await run(adapter, pool, { maxTurns: 5 });

    expect(callTool).not.toHaveBeenCalled();
    const toolMessage = result.messages.find((m) => m.role === 'tool');
    expect(toolMessage?.toolResults?.[0]?.isError).toBe(true);
    expect(toolMessage?.toolResults?.[0]?.content).toContain('truncated');
  });

  it('retries the same turn on a retryable error and then succeeds', async () => {
    const { adapter, calls } = scriptedAdapter([[retryableError], [doneEnd]]);
    const { pool } = fakePool();

    const result = await run(adapter, pool, { maxTurns: 5 });

    expect(result.stopReason).toBe('end');
    expect(result.turns).toBe(1);
    expect(calls()).toBeGreaterThan(1);
  });

  it('stops immediately on a non-retryable error with no retry', async () => {
    const { adapter, calls } = scriptedAdapter([[fatalError]]);
    const { pool } = fakePool();

    const result = await run(adapter, pool, { maxTurns: 5 });

    expect(result.stopReason).toBe('error');
    expect(calls()).toBe(1);
  });

  it('gives up after maxConsecutiveRetries on a persistently retryable error, never looping forever', async () => {
    // A provider that ALWAYS returns a retryable error must not retry without
    // bound: only the per-retry delay is capped by maxRetryDelayMs, so the
    // retry COUNT itself must have its own cap too.
    const { adapter, calls } = scriptedAdapter([[retryableError]]);
    const { pool } = fakePool();

    const result = await run(adapter, pool, { maxTurns: 50, maxConsecutiveRetries: 4 });

    expect(result.stopReason).toBe('error');
    expect(calls()).toBe(5); // 1 initial attempt + 4 retries, then give up
  });

  it('bounds malformed-tool-call reflection retries instead of looping forever', async () => {
    const { adapter, calls } = scriptedAdapter([[malformedError]]);
    const { pool } = fakePool();

    const result = await runLoop({
      adapter,
      pool,
      systemPrompt: 's',
      initialMessages: [{ role: 'user', content: 'go' }],
      config: { maxTurns: 100, maxConsecutiveReflections: 2 },
      sleep: noSleep,
    });

    expect(result.stopReason).toBe('error');
    // 2 reflection retries, then the 3rd malformed error exceeds the cap and stops.
    expect(calls()).toBe(3);
    expect(calls()).toBeLessThanOrEqual(3);
  });
});

describe('Retry-After', () => {
  /** Capture the delays a run actually waited, instead of sleeping. */
  function recordingRun(adapter: ProviderAdapter, config: Parameters<typeof runLoop>[0]['config']) {
    const slept: number[] = [];
    const events: Array<HarnessEvent | { type: 'loopEvent'; kind: string; detail?: string }> = [];
    const { pool } = fakePool();
    const result = runLoop({
      adapter,
      pool,
      systemPrompt: 'you are an agent',
      initialMessages: [{ role: 'user', content: 'apply to jobs' }],
      config,
      sleep: async (ms: number) => {
        slept.push(ms);
      },
      onEvent: (e) => events.push(e),
    });
    return { result, slept, events };
  }

  it("waits the provider's Retry-After instead of the computed curve", async () => {
    // The curve's first delay is ~1000-2000ms; the header asks for 30s.
    const { adapter } = scriptedAdapter([
      [{ type: 'error', message: '429 rate limit', retryable: true, retryAfterMs: 30_000 }],
      [doneEnd],
    ]);
    const { result, slept } = recordingRun(adapter, { maxTurns: 5 });
    await result;
    expect(slept[0]).toBe(30_000);
  });

  it('clamps a Retry-After that would park an unattended run', async () => {
    const { adapter } = scriptedAdapter([
      [{ type: 'error', message: '429 rate limit', retryable: true, retryAfterMs: 4 * 60 * 60 * 1000 }],
      [doneEnd],
    ]);
    const { result, slept } = recordingRun(adapter, { maxTurns: 5, maxRetryDelayMs: 60_000 });
    await result;
    expect(slept[0]).toBe(60_000);
  });

  it('falls back to exponential backoff when the provider sent no header', async () => {
    const { adapter } = scriptedAdapter([[retryableError], [doneEnd]]);
    const { result, slept } = recordingRun(adapter, { maxTurns: 5 });
    await result;
    expect(slept[0]).toBeGreaterThanOrEqual(1_000);
    expect(slept[0]).toBeLessThanOrEqual(2_000);
  });

  it('honours a zero Retry-After rather than treating it as absent', async () => {
    const { adapter } = scriptedAdapter([
      [{ type: 'error', message: '429 rate limit', retryable: true, retryAfterMs: 0 }],
      [doneEnd],
    ]);
    const { result, slept } = recordingRun(adapter, { maxTurns: 5 });
    await result;
    expect(slept[0]).toBe(0);
  });
});

describe('wrap-up window', () => {
  /** Collect the user-role messages a finished run accumulated. */
  const userTexts = (messages: ConversationMessage[]) =>
    messages.filter((m) => m.role === 'user').map((m) => m.content);

  it('warns the model once, two turns before the cap', async () => {
    const { adapter } = scriptedAdapter([[doneToolCalls()]]);
    const { pool } = fakePool();
    const events: Array<{ kind?: string }> = [];
    const result = await runLoop({
      adapter,
      pool,
      systemPrompt: 'you are an agent',
      initialMessages: [{ role: 'user', content: 'apply to jobs' }],
      config: { maxTurns: 5 },
      sleep: noSleep,
      onEvent: (e) => events.push(e as { kind?: string }),
    });
    expect(result.stopReason).toBe('turnCapReached');
    const warnings = userTexts(result.messages).filter((t) => t.includes('close to this run'));
    expect(warnings).toHaveLength(1);
    expect(events.filter((e) => e.kind === 'wrapUp')).toHaveLength(1);
  });

  it('does not extend the budget — the cap still stops the loop', async () => {
    const { adapter, calls } = scriptedAdapter([[doneToolCalls()]]);
    const { pool } = fakePool();
    const result = await run(adapter, pool, { maxTurns: 4 });
    expect(result.turns).toBe(4);
    expect(calls()).toBe(4);
  });

  it('stays silent when wrapUpTurns is 0', async () => {
    const { adapter } = scriptedAdapter([[doneToolCalls()]]);
    const { pool } = fakePool();
    const result = await run(adapter, pool, { maxTurns: 4, wrapUpTurns: 0 });
    expect(userTexts(result.messages).filter((t) => t.includes('close to this run'))).toHaveLength(0);
  });

  it('stays silent when the reserve would swallow the whole budget', async () => {
    // Otherwise a tiny cap would make every run a wind-down from turn one.
    const { adapter } = scriptedAdapter([[doneToolCalls()]]);
    const { pool } = fakePool();
    const result = await run(adapter, pool, { maxTurns: 2, wrapUpTurns: 2 });
    expect(userTexts(result.messages).filter((t) => t.includes('close to this run'))).toHaveLength(0);
  });

  it('delivers the warning as its own message, never appended to tool results', async () => {
    // The Messages API 400s when text precedes the tool_result blocks answering
    // a tool_use, so the warning must not share that message.
    const { adapter } = scriptedAdapter([[doneToolCalls()]]);
    const { pool } = fakePool();
    const result = await run(adapter, pool, { maxTurns: 3 });
    const warned = result.messages.find((m) => m.content.includes('close to this run'));
    expect(warned).toBeDefined();
    expect(warned?.role).toBe('user');
    expect(warned?.toolResults).toBeUndefined();
  });
});
