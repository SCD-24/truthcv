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
      text: async () => JSON.stringify(payload),
    })),
  );
}

/** Build a fetch stub returning a non-2xx with a verbatim body and headers. */
function stubFetchText(status: number, body: string, headers: Record<string, string> = {}): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => ({}),
      text: async () => body,
      headers: { get: (name: string) => headers[name.toLowerCase()] ?? null },
    })),
  );
}

/** Build a fetch stub that throws the way a network failure does.
 *
 * undici rejects with `TypeError: fetch failed` for DNS, TCP, TLS and reset
 * failures — the whole class where the request never reached the provider.
 */
function stubFetchThrowing(message = 'fetch failed'): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError(message);
    }),
  );
}

/** Build a fetch stub whose headers arrive and whose body then dies.
 *
 * undici's `terminated` — the socket closing mid-response. The request DID
 * reach the provider, but no answer was read, so it is as retryable as a
 * failed connect and must not escape the adapter either.
 */
function stubFetchBodyDying(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => {
        throw Object.assign(new TypeError('terminated'), {
          cause: new Error('other side closed'),
        });
      },
      text: async () => '',
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

  it('sends a subscription token with the Claude Code preamble first', async () => {
    // Without this block the Messages API answers 429 rate_limit_error with the
    // message "Error" — indistinguishable from an exhausted quota, and not one.
    stubFetch(200, { content: [{ type: 'text', text: 'ok' }], stop_reason: 'end_turn' });
    await collect(createAnthropicMessagesAdapter({ oauthToken: 'tok', model: 'claude' }));
    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const init = call[1] as { headers: Record<string, string>; body: string };
    const body = JSON.parse(init.body) as { system: Array<{ type: string; text: string }> };
    expect(body.system[0]).toEqual({
      type: 'text',
      text: "You are Claude Code, Anthropic's official CLI for Claude.",
    });
    expect(body.system[1]).toEqual({ type: 'text', text: 'you are a test' });
    expect(init.headers['anthropic-beta']).toBe('oauth-2025-04-20');
    expect(init.headers['authorization']).toBe('Bearer tok');
    expect(init.headers['x-api-key']).toBeUndefined();
  });

  it('leaves an API-key request on the plain string system prompt', async () => {
    stubFetch(200, { content: [{ type: 'text', text: 'ok' }], stop_reason: 'end_turn' });
    await collect(createAnthropicMessagesAdapter({ apiKey: 'k', model: 'claude' }));
    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const init = call[1] as { headers: Record<string, string>; body: string };
    expect(JSON.parse(init.body).system).toBe('you are a test');
    expect(init.headers['anthropic-beta']).toBeUndefined();
    expect(init.headers['x-api-key']).toBe('k');
  });

  it('omits an empty system prompt rather than sending an empty text block', async () => {
    stubFetch(200, { content: [{ type: 'text', text: 'ok' }], stop_reason: 'end_turn' });
    const adapter = createAnthropicMessagesAdapter({ oauthToken: 'tok', model: 'claude' });
    for await (const _ of adapter.sendMessage({ ...request, systemPrompt: '' })) void _;
    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse((call[1] as { body: string }).body) as { system: unknown[] };
    expect(body.system).toHaveLength(1);
  });

  it("carries the provider's own error message, not just the status", async () => {
    // Two 429s mean opposite things — wait, or top the account up — and only
    // the body says which. Reporting the status alone made them identical.
    stubFetchText(
      429,
      JSON.stringify({ type: 'error', error: { type: 'rate_limit_error', message: "This request would exceed your organization rate limit." } }),
    );
    const events = await collect(createAnthropicMessagesAdapter({ apiKey: 'k', model: 'claude' }));
    expect(events).toContainEqual({
      type: 'error',
      message:
        "Anthropic request failed with status 429: This request would exceed your organization rate limit.",
      retryable: true,
    });
  });

  it('falls back to the raw body when the error response is not JSON', async () => {
    stubFetchText(502, '<html>\n  <body>Bad gateway</body>\n</html>');
    const events = await collect(
      createOpenAiChatCompletionsAdapter({ apiKey: 'k', baseUrl: 'http://x', model: 'gpt' }),
    );
    expect(events).toContainEqual({
      type: 'error',
      message: 'OpenAI request failed with status 502: <html> <body>Bad gateway</body> </html>',
      retryable: true,
    });
  });

  it('truncates a long error body rather than flooding the run log', async () => {
    stubFetchText(500, JSON.stringify({ error: { message: 'x'.repeat(1000) } }));
    const events = await collect(createAnthropicMessagesAdapter({ apiKey: 'k', model: 'claude' }));
    const error = events.find((e) => e.type === 'error');
    expect(error?.type === 'error' && error.message.length).toBeLessThan(400);
    expect(error?.type === 'error' && error.message.endsWith('…')).toBe(true);
  });

  it('degrades to the status alone when the body cannot be read', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 503,
        json: async () => ({}),
        text: async () => {
          throw new Error('connection reset');
        },
      })),
    );
    const events = await collect(createAnthropicMessagesAdapter({ apiKey: 'k', model: 'claude' }));
    expect(events).toContainEqual({
      type: 'error',
      message: 'Anthropic request failed with status 503',
      retryable: true,
    });
  });

  it('carries a delta-seconds Retry-After through to the loop', async () => {
    stubFetchText(429, '{}', { 'retry-after': '42' });
    const events = await collect(createAnthropicMessagesAdapter({ apiKey: 'k', model: 'claude' }));
    const error = events.find((e) => e.type === 'error');
    expect(error?.type === 'error' && error.retryAfterMs).toBe(42_000);
    expect(error?.type === 'error' && error.message).toContain('retry-after 42s');
  });

  it('parses an HTTP-date Retry-After and never yields a negative wait', async () => {
    stubFetchText(503, '{}', { 'retry-after': 'Wed, 21 Oct 2015 07:28:00 GMT' });
    const events = await collect(
      createOpenAiChatCompletionsAdapter({ apiKey: 'k', baseUrl: 'http://x', model: 'gpt' }),
    );
    const error = events.find((e) => e.type === 'error');
    expect(error?.type === 'error' && error.retryAfterMs).toBe(0);
  });

  it('omits retryAfterMs when the header is absent or unparseable', async () => {
    stubFetchText(429, '{}');
    let events = await collect(createAnthropicMessagesAdapter({ apiKey: 'k', model: 'claude' }));
    let error = events.find((e) => e.type === 'error');
    expect(error?.type === 'error' && 'retryAfterMs' in error).toBe(false);

    stubFetchText(429, '{}', { 'retry-after': 'soon-ish' });
    events = await collect(createAnthropicMessagesAdapter({ apiKey: 'k', model: 'claude' }));
    error = events.find((e) => e.type === 'error');
    expect(error?.type === 'error' && 'retryAfterMs' in error).toBe(false);
  });
});

describe('a request that never reached the provider', () => {
  // A run died on 2026-08-28 at turn 33 of 400, ~105k tokens in, to a single
  // `fetch failed` — no response received, on a morning when the host's network
  // was demonstrably unstable (an AP roam with a DHCP restart, two resolver
  // degradations). Which packet was lost at that second is not knowable: the
  // cause was discarded before it reached the log, which is half of what this
  // change fixes. Every HTTP *response* the
  // provider sends becomes a retryable error event and is retried up to eight
  // times with backoff; a *thrown* fetch was the one class that escaped the
  // adapter entirely, past every retry, to the harness's outermost catch —
  // ending the run on the first blip. The failure most likely to be transient
  // had the least tolerance for being transient.
  it('reports an Anthropic network failure as a retryable event, not a throw', async () => {
    stubFetchThrowing();
    const events = await collect(createAnthropicMessagesAdapter({ apiKey: 'k', model: 'claude' }));
    const error = events.find((e) => e.type === 'error');
    expect(error).toBeDefined();
    expect(error).toMatchObject({ retryable: true });
    expect((error as { message: string }).message).toContain('fetch failed');
  });

  it('reports an OpenAI network failure as a retryable event, not a throw', async () => {
    stubFetchThrowing();
    const events = await collect(createOpenAiChatCompletionsAdapter({ apiKey: 'k', model: 'gpt', baseUrl: 'https://api.openai.com/v1' }));
    const error = events.find((e) => e.type === 'error');
    expect(error).toBeDefined();
    expect(error).toMatchObject({ retryable: true });
  });

  it('names the vendor and the cause, so the run log says which failed and why', async () => {
    stubFetchThrowing('getaddrinfo EAI_AGAIN api.anthropic.com');
    const events = await collect(createAnthropicMessagesAdapter({ apiKey: 'k', model: 'claude' }));
    const message = (events.find((e) => e.type === 'error') as { message: string }).message;
    expect(message).toContain('Anthropic');
    expect(message).toContain('EAI_AGAIN');
  });
});

describe('a response whose body dies mid-read', () => {
  // The other half of the same transient-socket class: headers arrive, the
  // socket closes before the body does. undici throws `terminated` here rather
  // than `fetch failed`, so guarding only the connect leaves this one exactly
  // as fatal as it was — on a long response over a flapping link, which is
  // where 100k-token answers live.
  it('is retryable for Anthropic, not a throw', async () => {
    stubFetchBodyDying();
    const events = await collect(createAnthropicMessagesAdapter({ apiKey: 'k', model: 'claude' }));
    const error = events.find((e) => e.type === 'error');
    expect(error).toMatchObject({ retryable: true });
    expect((error as { message: string }).message).toContain('terminated');
  });

  it('is retryable for OpenAI, not a throw', async () => {
    stubFetchBodyDying();
    const events = await collect(
      createOpenAiChatCompletionsAdapter({ apiKey: 'k', model: 'gpt', baseUrl: 'https://api.openai.com/v1' }),
    );
    expect(events.find((e) => e.type === 'error')).toMatchObject({ retryable: true });
  });
});
