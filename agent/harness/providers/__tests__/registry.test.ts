import { afterEach, describe, expect, it, vi } from 'vitest';

import { createProviderAdapter } from '../registry.js';
import type { HarnessEvent, ModelRequest } from '../types.js';

/** A minimal request; the canned response ignores its contents. */
const request: ModelRequest = {
  systemPrompt: 'you are a test',
  messages: [{ role: 'user', content: 'hi' }],
  tools: [],
};

/** Stub `fetch` with one canned success response and capture the request body sent. */
function stubFetchCapturingBody(): { body: () => unknown } {
  let captured: unknown;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) => {
      captured = init?.body ? JSON.parse(init.body as string) : undefined;
      return {
        ok: true,
        status: 200,
        json: async () => ({ choices: [{ message: { content: 'hi' }, finish_reason: 'stop' }], usage: {} }),
        text: async () => '',
        headers: { get: () => null },
      };
    }),
  );
  return { body: () => captured };
}

async function drain(adapter: { sendMessage: (r: ModelRequest) => AsyncGenerator<HarnessEvent> }): Promise<void> {
  for await (const _ of adapter.sendMessage(request)) {
    /* drain */
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('createProviderAdapter contextWindow forwarding (registry)', () => {
  it('forwards contextWindow as options.num_ctx for ollama', async () => {
    const { body } = stubFetchCapturingBody();
    const adapter = createProviderAdapter({
      provider: 'ollama',
      wire: 'openai-chat-completions',
      model: 'llama3',
      token: '',
      baseUrl: 'http://localhost:11434/v1',
      contextWindow: 8192,
    });

    await drain(adapter);

    expect((body() as { options?: { num_ctx?: number } }).options?.num_ctx).toBe(8192);
  });

  it('does not forward contextWindow to OpenRouter', async () => {
    const { body } = stubFetchCapturingBody();
    const adapter = createProviderAdapter({
      provider: 'openrouter',
      wire: 'openai-chat-completions',
      model: 'x/y',
      token: 'tok',
      baseUrl: '',
      contextWindow: 128000,
    });

    await drain(adapter);

    expect((body() as { options?: unknown }).options).toBeUndefined();
  });
});
