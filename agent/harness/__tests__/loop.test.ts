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

  it('threads the screening adapter through to a screen_posting tool call', async () => {
    // The screening adapter is threaded explicitly through RunLoopOptions ->
    // executeTurnToolCalls -> executeToolCall, never read from any
    // module-level state, so this proves the wiring actually reaches the
    // screen_posting branch rather than just documenting the intent.
    const screenCall: ToolCall = {
      id: 'sc1',
      name: 'screen_posting',
      arguments: {
        url: 'https://example.com/jobs/1',
        role: 'Engineer',
        company: 'Acme',
        postingText: 'Fully remote.',
        profile: 'Backend',
        criteria: 'remote_model: remote',
      },
    };
    const verdictJson = JSON.stringify({
      verdict: 'passed',
      screeningBlocker: '',
      failingCriterion: '',
      reason: 'ok',
      remoteArrangement: 'remote',
      languageRequirement: '',
    });
    const screeningAdapter: ProviderAdapter = {
      async *sendMessage() {
        yield { type: 'done', stopReason: 'end', message: { role: 'assistant', content: verdictJson } };
      },
    };
    const { adapter } = scriptedAdapter([
      [
        { type: 'toolCall', toolCall: screenCall },
        { type: 'done', stopReason: 'toolCalls', message: { role: 'assistant', content: '', toolCalls: [screenCall] } },
      ],
      [doneEnd],
    ]);
    const { pool } = fakePool();

    const result = await runLoop({
      adapter,
      pool,
      systemPrompt: 'you are an agent',
      initialMessages: [{ role: 'user', content: 'go' }],
      config: { maxTurns: 5 },
      sleep: noSleep,
      screeningAdapter,
    });

    const toolMessage = result.messages.find((m) => m.role === 'tool');
    const screenResult = toolMessage?.toolResults?.find((r) => r.toolCallId === 'sc1');
    expect(screenResult?.isError).toBe(false);
    expect(JSON.parse(screenResult?.content ?? '{}').verdict).toBe('passed');
  });

  it('reports screen_posting as unconfigured when no screening adapter is given', async () => {
    const screenCall: ToolCall = {
      id: 'sc1',
      name: 'screen_posting',
      arguments: {
        url: 'https://example.com/jobs/1',
        role: 'Engineer',
        company: 'Acme',
        postingText: 'Fully remote.',
        profile: 'Backend',
        criteria: 'remote_model: remote',
      },
    };
    const { adapter } = scriptedAdapter([
      [
        { type: 'toolCall', toolCall: screenCall },
        { type: 'done', stopReason: 'toolCalls', message: { role: 'assistant', content: '', toolCalls: [screenCall] } },
      ],
      [doneEnd],
    ]);
    const { pool } = fakePool();

    const result = await run(adapter, pool, { maxTurns: 5 });

    const toolMessage = result.messages.find((m) => m.role === 'tool');
    const screenResult = toolMessage?.toolResults?.find((r) => r.toolCallId === 'sc1');
    expect(screenResult?.isError).toBe(true);
    expect(screenResult?.content).toContain('not configured');
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

describe('a turn that produced nothing at all', () => {
  // The 2026-08-30 incident: a router swapped in a reasoning model, which
  // answered with an empty `content`, no tool calls and finish_reason 'stop'.
  // The loop read that non-event as a deliberate finish and abandoned three
  // approved applications after six turns.

  /** A `done` event for a turn with neither text nor tool calls. */
  const doneEmpty: HarnessEvent = {
    type: 'done',
    stopReason: 'end',
    message: { role: 'assistant', content: '' },
  };

  /** A tool call that closes the run, matching the loop's finish_run latch. */
  const FINISH_RUN_CALL: ToolCall = { id: 'f1', name: 'truthcv__finish_run', arguments: {} };

  /** A `done` event whose single tool call is the run-closing one. */
  function doneFinishRun(): HarnessEvent {
    return {
      type: 'done',
      stopReason: 'toolCalls',
      message: { role: 'assistant', content: '', toolCalls: [FINISH_RUN_CALL] },
    };
  }

  /** A pool that also allows `finish_run`, so the loop can latch its execution. */
  function poolWithFinishRun() {
    const { pool, callTool } = fakePool();
    const tools: NamespacedTool[] = [
      ...pool.listTools(),
      { namespacedName: 'truthcv__finish_run', serverName: 'truthcv', toolName: 'finish_run', description: 'd', inputSchema: { type: 'object' } },
    ];
    return { pool: { ...pool, listTools: () => tools } as unknown as McpClientPool, callTool };
  }

  /** The user-role message contents a finished run accumulated. */
  const userTexts = (messages: ConversationMessage[]) =>
    messages.filter((m) => m.role === 'user').map((m) => m.content);

  it('nudges the model and keeps going instead of ending the run', async () => {
    const { adapter, calls } = scriptedAdapter([[doneEmpty], [doneToolCalls()], [doneEnd]]);
    const { pool } = fakePool();

    const result = await run(adapter, pool, { maxTurns: 10 });

    expect(result.stopReason).toBe('end');
    expect(calls()).toBe(3);
    expect(userTexts(result.messages).filter((t) => t.includes('no content and no tool calls'))).toHaveLength(1);
  });

  it('reports the nudge as a loop event so a run log shows what happened', async () => {
    const { adapter } = scriptedAdapter([[doneEmpty], [doneEnd]]);
    const { pool } = fakePool();
    const kinds: string[] = [];

    await runLoop({
      adapter,
      pool,
      systemPrompt: 'you are an agent',
      initialMessages: [{ role: 'user', content: 'apply to jobs' }],
      config: { maxTurns: 10 },
      sleep: noSleep,
      onEvent: (e) => {
        if ('kind' in e) kinds.push(e.kind);
      },
    });

    expect(kinds).toContain('emptyTurn');
  });

  it('starts the empty-turn budget again after a turn that produced something', async () => {
    // The cap counts CONSECUTIVE empty turns: a recovered model that later
    // returns one more empty turn must be nudged again, not counted toward a
    // cap it never got near.
    const { adapter } = scriptedAdapter([
      [doneEmpty],
      [doneToolCalls()],
      [doneEmpty],
      [doneToolCalls()],
      [doneEnd],
    ]);
    const { pool, callTool } = fakePool();

    const result = await run(adapter, pool, { maxTurns: 20, maxConsecutiveEmptyTurns: 1 });

    expect(result.stopReason).toBe('end');
    expect(callTool).toHaveBeenCalledTimes(2);
    expect(userTexts(result.messages).filter((t) => t.includes('no content and no tool calls'))).toHaveLength(2);
  });

  it('counts only the empty turns since the last productive one toward the cap', async () => {
    // The companion to the test above, and the one that pins the reset down to
    // being CONDITIONAL: a reset on every turn would keep the streak at one
    // forever, so the cap could never be reached and only `maxTurns` would
    // ever stop the run. `maxTurns` is set well above the scripted turns so
    // that failure shows up as a wrong stop reason rather than a hang.
    const { adapter, calls } = scriptedAdapter([
      [doneEmpty],
      [doneToolCalls()],
      [doneEmpty],
      [doneEmpty],
      [doneEmpty],
    ]);
    const { pool } = fakePool();

    const result = await run(adapter, pool, { maxTurns: 8, maxConsecutiveEmptyTurns: 2 });

    // The first empty turn is nudged and then forgotten; the three that follow
    // the tool call are the streak, and the third of them exceeds the cap.
    expect(result.stopReason).toBe('end');
    expect(result.turns).toBe(5);
    expect(calls()).toBe(5);
  });

  it('spends nudged turns against the hard cap instead of running past it', async () => {
    // A nudge is a provider request like any other, so an empty-turn streak
    // must not buy turns beyond `maxTurns` — the one bound an unattended
    // overnight run has. It must also still enter the wrap-up window, and stop
    // as `turnCapReached` (exit 2) rather than as an unfinished run (exit 6),
    // so the supervisor names the right cause.
    const { adapter, calls } = scriptedAdapter([[doneToolCalls()], [doneEmpty]]);
    const { pool } = fakePool();
    const kinds: string[] = [];

    const result = await runLoop({
      adapter,
      pool,
      systemPrompt: 'you are an agent',
      initialMessages: [{ role: 'user', content: 'apply to jobs' }],
      config: { maxTurns: 3, wrapUpTurns: 1 },
      sleep: noSleep,
      onEvent: (e) => {
        if ('kind' in e) kinds.push(e.kind);
      },
    });

    expect(result.turns).toBe(3);
    expect(calls()).toBe(3);
    expect(result.stopReason).toBe('turnCapReached');
    expect(kinds).toContain('wrapUp');
  });

  it('gives up as an unfinished run once the empty turns exceed the cap, rather than nudging forever', async () => {
    const { adapter, calls } = scriptedAdapter([[doneEmpty]]);
    const { pool } = fakePool();

    const result = await run(adapter, pool, { maxTurns: 100, maxConsecutiveEmptyTurns: 2 });

    // 'end' with no finish_run is what cli.ts reports as an unfinished run;
    // 'error' would misname a model that stopped producing as a provider fault.
    expect(result.stopReason).toBe('end');
    expect(result.finishRunExecuted).toBe(false);
    expect(calls()).toBe(3); // the first empty turn, two nudged retries, then it stops
  });

  it('ends immediately on an empty turn once finish_run has executed, without nudging', async () => {
    // Nudging here could restart a run that already reported its outcome and
    // submit duplicate applications under a real person's name.
    const { adapter, calls } = scriptedAdapter([[doneFinishRun()], [doneEmpty]]);
    const { pool } = poolWithFinishRun();

    const result = await run(adapter, pool, { maxTurns: 10 });

    expect(result.stopReason).toBe('end');
    expect(result.finishRunExecuted).toBe(true);
    expect(calls()).toBe(2);
    expect(userTexts(result.messages).filter((t) => t.includes('no content and no tool calls'))).toHaveLength(0);
  });
});

describe('a network failure the adapter reports instead of throwing', () => {
  // The end-to-end shape of the 2026-08-28 outage: no answer came back, so the
  // adapter reports it as retryable rather than throwing past the loop. The run
  // must survive it, not end on it. Eight attempts with capped backoff is ~183s
  // of tolerance, against a disruption window the host journal puts at ~90s.
  it('backs off and carries on, rather than ending the run', async () => {
    const networkError: HarnessEvent = {
      type: 'error',
      message: 'Anthropic request could not be sent: fetch failed: getaddrinfo EAI_AGAIN',
      retryable: true,
    };
    const { adapter, calls } = scriptedAdapter([[networkError], [doneEnd]]);
    const { pool } = fakePool();

    const result = await run(adapter, pool, { maxTurns: 5 });

    expect(result.stopReason).toBe('end');
    expect(calls()).toBeGreaterThan(1);
  });
});

describe('compaction the provider asks for', () => {
  // The path that needs no configuration: the provider says the context is too
  // long, so no window number and no estimate can be wrong. It is the only
  // cover for a run whose window nobody stated, and the backstop for one whose
  // estimate ran under — which it will, on dense JSON tool results.
  const overflow: HarnessEvent = {
    type: 'error',
    message: 'Anthropic request failed with status 400: prompt is too long: 214000 tokens > 200000 maximum',
    retryable: false,
  };

  function longConversation() {
    return Array.from({ length: 40 }, (_, i) => ({
      role: (i % 2 === 0 ? 'user' : 'assistant') as 'user' | 'assistant',
      content: `turn ${i} `.repeat(50),
    }));
  }

  it('compacts and resends instead of ending the run', async () => {
    const { adapter, calls } = scriptedAdapter([[overflow], [doneEnd]]);
    const { pool } = fakePool();

    const result = await runLoop({
      adapter,
      pool,
      systemPrompt: 'you are an agent',
      initialMessages: longConversation(),
      config: { maxTurns: 5 },
      sleep: async () => {},
    });

    expect(result.stopReason).toBe('end');
    expect(calls()).toBeGreaterThan(1);
  });

  it('reports the compaction it was forced into', async () => {
    const { adapter } = scriptedAdapter([[overflow], [doneEnd]]);
    const { pool } = fakePool();
    const events: string[] = [];

    await runLoop({
      adapter,
      pool,
      systemPrompt: 'you are an agent',
      initialMessages: longConversation(),
      config: { maxTurns: 5 },
      sleep: async () => {},
      onEvent: (e) => {
        if ('kind' in e && e.kind === 'compaction') events.push(e.detail ?? '');
      },
    });

    expect(events).toHaveLength(1);
    expect(events[0]).toContain('provider reported the context was too long');
  });

  it('gives up when there is nothing left to compact, rather than spinning', async () => {
    // Already at the floor: the pinned instructions plus the recent turns.
    // Compacting removes nothing, so resending would be byte-identical.
    const { adapter, calls } = scriptedAdapter([[overflow]]);
    const { pool } = fakePool();
    const stops: string[] = [];

    const result = await runLoop({
      adapter,
      pool,
      systemPrompt: 'you are an agent',
      initialMessages: [{ role: 'user', content: 'instructions' }],
      config: { maxTurns: 5 },
      sleep: async () => {},
      onEvent: (e) => {
        if ('kind' in e && e.kind === 'stop') stops.push(e.detail ?? '');
      },
    });

    expect(result.stopReason).toBe('error');
    expect(calls()).toBe(1);
    // Asserting the reason, not just the failure: pre-change this message
    // classified as a plain bad-request and also ended the run after one
    // request, so stopReason alone cannot tell the two apart.
    expect(stops).toContain('context overflow with nothing left to compact');
  });

  it('stops once compacting stops helping, without exhausting the cap', () => {
    // Compaction is single-pass: after one pass the history is already at its
    // floor (pinned instructions + summary + KEEP_RECENT), so a second pass
    // removes nothing. The "did it actually shrink" check is therefore the
    // bound that fires in practice, and maxOverflowCompactions is the
    // secondary guard for a compactor that does keep shrinking.
    return (async () => {
      const { adapter, calls } = scriptedAdapter([[overflow]]);
      const { pool } = fakePool();

      const result = await runLoop({
        adapter,
        pool,
        systemPrompt: 'you are an agent',
        initialMessages: longConversation(),
        config: { maxTurns: 50, maxOverflowCompactions: 5 },
        sleep: async () => {},
      });

      expect(result.stopReason).toBe('error');
      // The original attempt, one compaction, one resend — then it stops.
      expect(calls()).toBe(2);
    })();
  });

  it('starts the overflow budget again after a turn the provider accepted', async () => {
    // The budget guards a conversation that will not shrink, not a long run
    // that legitimately overflows more than three times.
    const overflowThenWork: HarnessEvent[][] = [];
    for (let i = 0; i < 5; i += 1) overflowThenWork.push([overflow], [doneToolCalls()], [doneEnd]);
    const { adapter } = scriptedAdapter(overflowThenWork);
    const { pool } = fakePool();

    const result = await runLoop({
      adapter,
      pool,
      systemPrompt: 'you are an agent',
      initialMessages: longConversation(),
      config: { maxTurns: 50, maxOverflowCompactions: 1 },
      sleep: async () => {},
    });

    expect(result.stopReason).toBe('end');
  });
});

describe('executeTurnToolCalls concurrency (via runLoop)', () => {
  /** A pending call's resolver, released explicitly by the test. */
  type Releaser = (result: { content: string; isError?: boolean }) => void;

  /**
   * A controllable MCP pool: every `callTool` call is deferred until the test
   * releases it by namespaced name, and per-server in-flight counts are
   * tracked so a peak above 1 is direct, deterministic evidence of overlap
   * (no real timers or sleeps involved anywhere).
   */
  function controllablePool(tools: NamespacedTool[]) {
    const active = new Map<string, number>();
    const peak = new Map<string, number>();
    const releasers = new Map<string, Releaser>();
    const callTool = vi.fn((namespacedName: string) => {
      const server = namespacedName.split('__')[0];
      const count = (active.get(server) ?? 0) + 1;
      active.set(server, count);
      peak.set(server, Math.max(peak.get(server) ?? 0, count));
      return new Promise((resolve) => {
        releasers.set(namespacedName, (result) => {
          active.set(server, (active.get(server) ?? 1) - 1);
          resolve(result);
        });
      });
    });
    const release = (name: string, result: { content: string; isError?: boolean } = { content: 'ok', isError: false }) =>
      releasers.get(name)?.(result);
    const refreshTools = vi.fn(async () => {});
    const listTools = () => tools;
    const pool = { callTool, refreshTools, listTools } as unknown as McpClientPool;
    return { pool, callTool, release, peak };
  }

  /** Spin on microtasks (no real timer) until `mock` has been called `count` times. */
  async function waitUntilCalled(mock: { mock: { calls: unknown[] } }, count: number): Promise<void> {
    for (let i = 0; i < 10_000 && mock.mock.calls.length < count; i += 1) await Promise.resolve();
  }

  /** Build a namespaced tool + matching ToolCall for one server/tool pair. */
  function toolAndCall(serverName: string, toolName: string, id: string): { tool: NamespacedTool; call: ToolCall } {
    const namespacedName = `${serverName}__${toolName}`;
    return {
      tool: { namespacedName, serverName, toolName, description: '', inputSchema: { type: 'object' } },
      call: { id, name: namespacedName, arguments: {} },
    };
  }

  /** A one-turn `toolCalls` script followed by a closing `end` turn. */
  function turnRequesting(calls: ToolCall[]): HarnessEvent[][] {
    return [[{ type: 'done', stopReason: 'toolCalls', message: { role: 'assistant', content: '', toolCalls: calls } }], [doneEnd]];
  }

  it('runs several truthcv tool calls concurrently within one turn', async () => {
    const pairs = ['check_cooldown', 'get_job_profiles', 'get_company_findings'].map((n, i) =>
      toolAndCall('truthcv', n, `c${i}`),
    );
    const { pool, callTool, release, peak } = controllablePool(pairs.map((p) => p.tool));
    const { adapter } = scriptedAdapter(turnRequesting(pairs.map((p) => p.call)));

    const resultPromise = run(adapter, pool, { maxTurns: 5 });
    await waitUntilCalled(callTool, pairs.length);
    expect(peak.get('truthcv')).toBeGreaterThan(1);
    for (const { call } of pairs) release(call.name);

    await resultPromise;
  });

  it('returns tool results in request order even when they complete out of order', async () => {
    const pairs = ['check_cooldown', 'get_job_profiles', 'get_company_findings'].map((n, i) =>
      toolAndCall('truthcv', n, `c${i}`),
    );
    const { pool, callTool, release } = controllablePool(pairs.map((p) => p.tool));
    const { adapter } = scriptedAdapter(turnRequesting(pairs.map((p) => p.call)));

    const resultPromise = run(adapter, pool, { maxTurns: 5 });
    await waitUntilCalled(callTool, pairs.length);
    // Resolve out of request order: third, first, second.
    release(pairs[2].call.name, { content: 'third', isError: false });
    release(pairs[0].call.name, { content: 'first', isError: false });
    release(pairs[1].call.name, { content: 'second', isError: false });

    const result = await resultPromise;
    const toolMessage = result.messages.find((m) => m.role === 'tool');
    expect(toolMessage?.toolResults?.map((r) => r.toolCallId)).toEqual(['c0', 'c1', 'c2']);
    expect(toolMessage?.toolResults?.map((r) => r.content)).toEqual(['first', 'second', 'third']);
  });

  it('still runs tool calls when maxToolConcurrency is 0, clamped to at least 1', async () => {
    // A non-positive concurrency must never starve the pool down to zero
    // workers: that would resolve immediately, leave every call unexecuted,
    // and ship a sparse tool-results array that a provider adapter
    // dereferences as a TypeError (see loop.ts's runPool).
    const pairs = ['check_cooldown', 'get_job_profiles'].map((n, i) => toolAndCall('truthcv', n, `c${i}`));
    const { pool, callTool, release } = controllablePool(pairs.map((p) => p.tool));
    const { adapter } = scriptedAdapter(turnRequesting(pairs.map((p) => p.call)));

    const resultPromise = run(adapter, pool, { maxTurns: 5, maxToolConcurrency: 0 });
    // Clamped to exactly one worker, so the calls run serially: release each
    // in turn rather than waiting for both to start at once.
    await waitUntilCalled(callTool, 1);
    release(pairs[0].call.name);
    await waitUntilCalled(callTool, 2);
    release(pairs[1].call.name);

    const result = await resultPromise;
    const toolMessage = result.messages.find((m) => m.role === 'tool');
    expect(toolMessage?.toolResults?.map((r) => r.toolCallId)).toEqual(['c0', 'c1']);
    // Array.prototype.every SKIPS holes, so it would pass on a sparse array;
    // check length and each index explicitly instead, which does not.
    const results = toolMessage?.toolResults ?? [];
    expect(results).toHaveLength(2);
    for (let i = 0; i < results.length; i += 1) {
      expect(results[i]).toBeDefined();
    }
  });

  it('never overlaps two browser tool calls', async () => {
    const pairs = ['browser_navigate', 'browser_click'].map((n, i) => toolAndCall('browser', n, `c${i}`));
    const { pool, callTool, release, peak } = controllablePool(pairs.map((p) => p.tool));
    const { adapter } = scriptedAdapter(turnRequesting(pairs.map((p) => p.call)));

    const resultPromise = run(adapter, pool, { maxTurns: 5 });
    await waitUntilCalled(callTool, 1);
    expect(callTool.mock.calls.length).toBe(1); // the second must not have started yet
    release(pairs[0].call.name);
    await waitUntilCalled(callTool, 2);
    expect(peak.get('browser')).toBe(1);
    release(pairs[1].call.name);

    await resultPromise;
  });

  it('never overlaps harvest_postings\' internal browser calls with a model-issued browser call in the same turn', async () => {
    // harvest_postings is a `builtin`-server tool, not `browser`, but its
    // execution drives the browser internally via pool.callTool. Before the
    // fix it was dispatched through the unbounded "other" pool, so its
    // internal browser__* calls could interleave with a model-issued
    // browser__browser_click in the same turn — this reproduces exactly that
    // turn and proves the two now never overlap.
    const stderrSpy = vi.spyOn(process.stderr, 'write').mockImplementation(() => true);
    const browserClick = toolAndCall('browser', 'browser_click', 'c0');
    const harvestCall: ToolCall = {
      id: 'c1',
      name: 'harvest_postings',
      arguments: { boards: [{ board: 'Acme', url: 'https://acme.example/jobs' }] },
    };
    // No tab-management tools advertised, so harvest_postings takes the
    // degraded serial path: exactly one browser_navigate then one
    // browser_snapshot call, both internal.
    const browserTools = [
      'browser_navigate',
      'browser_click',
      'browser_type',
      'browser_file_upload',
      'browser_snapshot',
      'browser_take_screenshot',
      'browser_wait_for',
      'browser_press_key',
      'browser_select_option',
      'browser_handle_dialog',
    ].map((toolName) => toolAndCall('browser', toolName, toolName).tool);
    const { pool, callTool, release, peak } = controllablePool(browserTools);
    const { adapter } = scriptedAdapter(turnRequesting([browserClick.call, harvestCall]));

    const resultPromise = run(adapter, pool, { maxTurns: 5 });
    await waitUntilCalled(callTool, 1);
    expect(callTool.mock.calls[0][0]).toBe('browser__browser_click');
    release(browserClick.call.name);
    await waitUntilCalled(callTool, 2);
    expect(peak.get('browser')).toBe(1); // never more than one browser call in flight
    expect(callTool.mock.calls[1][0]).toBe('browser__browser_navigate');
    release('browser__browser_navigate', { content: 'ok', isError: false });
    await waitUntilCalled(callTool, 3);
    expect(peak.get('browser')).toBe(1);
    expect(callTool.mock.calls[2][0]).toBe('browser__browser_snapshot');
    release('browser__browser_snapshot', { content: 'no jobs found', isError: false });

    await resultPromise;
    expect(peak.get('browser')).toBe(1);
    stderrSpy.mockRestore();
  });

  it('still returns results for the other calls when one call rejects', async () => {
    const pairs = ['check_cooldown', 'get_job_profiles'].map((n, i) => toolAndCall('truthcv', n, `c${i}`));
    const callTool = vi.fn((namespacedName: string) =>
      namespacedName === pairs[0].tool.namespacedName
        ? Promise.reject(new Error('boom'))
        : Promise.resolve({ content: 'ok', isError: false }),
    );
    const pool = {
      callTool,
      refreshTools: vi.fn(async () => {}),
      listTools: () => pairs.map((p) => p.tool),
    } as unknown as McpClientPool;
    const { adapter } = scriptedAdapter(turnRequesting(pairs.map((p) => p.call)));

    const result = await run(adapter, pool, { maxTurns: 5 });
    const toolMessage = result.messages.find((m) => m.role === 'tool');
    expect(toolMessage?.toolResults?.[0]).toMatchObject({ toolCallId: 'c0', isError: true });
    expect(toolMessage?.toolResults?.[0]?.content).toContain('boom');
    expect(toolMessage?.toolResults?.[1]).toMatchObject({ toolCallId: 'c1', isError: false });
  });

  it('still latches finish_run when its result arrives after another call completes', async () => {
    const other = toolAndCall('truthcv', 'check_cooldown', 'c0');
    const finish = toolAndCall('truthcv', 'finish_run', 'c1');
    const { pool, callTool, release } = controllablePool([other.tool, finish.tool]);
    const { adapter } = scriptedAdapter(turnRequesting([other.call, finish.call]));

    const resultPromise = run(adapter, pool, { maxTurns: 5 });
    await waitUntilCalled(callTool, 2);
    // The finish_run result arrives LAST, after the other call's result.
    release(other.call.name, { content: 'ok', isError: false });
    release(finish.call.name, { content: 'closed', isError: false });

    const result = await resultPromise;
    expect(result.finishRunExecuted).toBe(true);
  });
});
