import { afterEach, describe, expect, it, vi } from 'vitest';

import { createAnthropicMessagesAdapter } from '../anthropicMessages.js';
import { createOpenAiChatCompletionsAdapter } from '../openaiChatCompletions.js';
import type { HarnessEvent, ModelRequest, ProviderAdapter } from '../types.js';

/** A minimal request; the canned responses ignore its contents. */
const request: ModelRequest = {
  systemPrompt: 'you are a test',
  messages: [{ role: 'user', content: 'call foo' }],
  tools: [{ name: 'foo', description: 'the foo tool', inputSchema: { type: 'object' } }],
};

/** Build a fetch stub returning one canned JSON response. */
function stubFetch(status: number, payload: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => payload,
    })),
  );
}

/** Drive an adapter to completion and collect every yielded event. */
async function collect(adapter: ProviderAdapter): Promise<HarnessEvent[]> {
  const events: HarnessEvent[] = [];
  for await (const event of adapter.sendMessage(request)) events.push(event);
  return events;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('provider adapters', () => {
  it('normalises an Anthropic tool_use block into a toolCall event', async () => {
    stubFetch(200, {
      content: [{ type: 'tool_use', id: 'anthropic-1', name: 'foo', input: { x: 1 } }],
      usage: { input_tokens: 3, output_tokens: 5 },
      stop_reason: 'tool_use',
    });
    const events = await collect(createAnthropicMessagesAdapter({ apiKey: 'k', model: 'claude' }));
    const toolCall = events.find((e) => e.type === 'toolCall');
    expect(toolCall).toEqual({ type: 'toolCall', toolCall: { id: 'anthropic-1', name: 'foo', arguments: { x: 1 } } });
    expect(events.at(-1)).toMatchObject({ type: 'done', stopReason: 'toolCalls' });
  });

  it('normalises an OpenAI tool_calls entry into a toolCall event', async () => {
    stubFetch(200, {
      choices: [
        {
          message: {
            content: null,
            tool_calls: [{ id: 'openai-1', function: { name: 'foo', arguments: '{"x":1}' } }],
          },
          finish_reason: 'tool_calls',
        },
      ],
      usage: { prompt_tokens: 3, completion_tokens: 5 },
    });
    const events = await collect(
      createOpenAiChatCompletionsAdapter({ apiKey: 'k', baseUrl: 'http://x', model: 'gpt' }),
    );
    const toolCall = events.find((e) => e.type === 'toolCall');
    expect(toolCall).toEqual({ type: 'toolCall', toolCall: { id: 'openai-1', name: 'foo', arguments: { x: 1 } } });
    expect(events.at(-1)).toMatchObject({ type: 'done', stopReason: 'toolCalls' });
  });

  it('produces the same-shaped toolCall event from both vendor payloads', async () => {
    stubFetch(200, {
      content: [{ type: 'tool_use', id: 'a', name: 'foo', input: { x: 1 } }],
      stop_reason: 'tool_use',
    });
    const anthropic = await collect(createAnthropicMessagesAdapter({ apiKey: 'k', model: 'claude' }));
    stubFetch(200, {
      choices: [
        { message: { tool_calls: [{ id: 'b', function: { name: 'foo', arguments: '{"x":1}' } }] }, finish_reason: 'tool_calls' },
      ],
    });
    const openai = await collect(
      createOpenAiChatCompletionsAdapter({ apiKey: 'k', baseUrl: 'http://x', model: 'gpt' }),
    );
    const pick = (events: HarnessEvent[]) => {
      const found = events.find((e) => e.type === 'toolCall');
      return found?.type === 'toolCall' ? { name: found.toolCall.name, arguments: found.toolCall.arguments } : undefined;
    };
    expect(pick(anthropic)).toEqual({ name: 'foo', arguments: { x: 1 } });
    expect(pick(openai)).toEqual(pick(anthropic));
  });

  it('yields an error event on a non-2xx Anthropic response instead of throwing', async () => {
    stubFetch(500, {});
    const events = await collect(createAnthropicMessagesAdapter({ apiKey: 'k', model: 'claude' }));
    expect(events).toContainEqual({ type: 'error', message: expect.any(String), retryable: true });
  });

  it('yields a non-retryable error event on a 4xx OpenAI response', async () => {
    stubFetch(400, {});
    const events = await collect(
      createOpenAiChatCompletionsAdapter({ apiKey: 'k', baseUrl: 'http://x', model: 'gpt' }),
    );
    expect(events).toContainEqual({ type: 'error', message: expect.any(String), retryable: false });
  });
});
