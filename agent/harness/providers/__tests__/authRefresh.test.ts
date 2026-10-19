import { describe, expect, it, vi } from 'vitest';

import { createAppTokenRefresher, createRefreshingAdapterFactory, withAuthRefresh } from '../authRefresh.js';
import { createProviderAdapter, type ProviderAdapterOptions } from '../registry.js';
import type { HarnessEvent, ModelRequest, ProviderAdapter } from '../types.js';

const request: ModelRequest = { systemPrompt: 's', messages: [{ role: 'user', content: 'hi' }], tools: [] };
const OLD = 'old-secret-token';
const NEW = 'new-secret-token';

const oauthOpts: ProviderAdapterOptions = {
  provider: 'claude',
  wire: 'anthropic-messages',
  model: 'm',
  token: OLD,
  baseUrl: '',
  authType: 'oauth',
};

const err401: HarnessEvent = { type: 'error', message: 'Claude request failed with status 401: bad', retryable: false };
const ok: HarnessEvent = { type: 'text', delta: 'ok' };

/** Adapter whose events depend on the token it was built with. */
function tokenAdapter(eventsFor: (token: string) => HarnessEvent[]) {
  const builtWith: string[] = [];
  const build = (o: ProviderAdapterOptions): ProviderAdapter => {
    builtWith.push(o.token);
    return {
      async *sendMessage() {
        yield* eventsFor(o.token);
      },
    };
  };
  return { build, builtWith };
}

async function collect(a: ProviderAdapter): Promise<HarnessEvent[]> {
  const out: HarnessEvent[] = [];
  for await (const e of a.sendMessage(request)) out.push(e);
  return out;
}

const okRefresher = { refresh: vi.fn(async () => NEW) };

describe('withAuthRefresh', () => {
  it('passes through for api_key auth', async () => {
    const refresher = { refresh: vi.fn(async () => NEW) };
    const { build, builtWith } = tokenAdapter(() => [err401]);
    const events = await collect(withAuthRefresh({ ...oauthOpts, authType: 'api_key' }, build, refresher));
    expect(events).toEqual([err401]);
    expect(refresher.refresh).not.toHaveBeenCalled();
    expect(builtWith).toEqual([OLD]);
  });

  it('refreshes on 401, retries, and later calls use the new token', async () => {
    const refresher = { refresh: vi.fn(async () => NEW) };
    const { build, builtWith } = tokenAdapter((t) => (t === OLD ? [err401] : [ok]));
    const adapter = withAuthRefresh(oauthOpts, build, refresher);
    expect(await collect(adapter)).toEqual([ok]);
    expect(refresher.refresh).toHaveBeenCalledWith('claude', OLD);
    expect(await collect(adapter)).toEqual([ok]);
    expect(refresher.refresh).toHaveBeenCalledTimes(1);
    expect(builtWith).toEqual([OLD, NEW]);
  });

  it('emits a non-retryable reconnect error containing 401 when refresh fails', async () => {
    const refresher = { refresh: vi.fn(async () => { throw new Error('needs reconnecting.'); }) };
    const { build } = tokenAdapter(() => [err401]);
    const events = await collect(withAuthRefresh(oauthOpts, build, refresher));
    expect(events).toHaveLength(1);
    const e = events[0] as Extract<HarnessEvent, { type: 'error' }>;
    expect(e.retryable).toBe(false);
    expect(e.message).toContain('401');
    expect(e.message).toContain('Claude');
    expect(e.message).toContain('needs reconnecting.');
    expect(e.message).not.toContain(OLD);
  });

  it('does not attempt a third call when the retry also 401s', async () => {
    const refresher = { refresh: vi.fn(async () => NEW) };
    const send = vi.fn();
    const build = (): ProviderAdapter => ({
      async *sendMessage() {
        send();
        yield err401;
      },
    });
    const events = await collect(withAuthRefresh({ ...oauthOpts, provider: 'codex', wire: 'openai-responses' }, build, refresher));
    expect(send).toHaveBeenCalledTimes(2);
    expect(refresher.refresh).toHaveBeenCalledTimes(1);
    expect(events).toHaveLength(1);
    expect((events[0] as { message: string }).message).toContain('ChatGPT');
    expect((events[0] as { message: string }).message).toContain('401');
  });

  it('reuses a token another request already refreshed without refreshing again', async () => {
    const refresher = { refresh: vi.fn(async () => NEW) };
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    let oldCalls = 0;
    const builtWith: string[] = [];
    const build = (o: ProviderAdapterOptions): ProviderAdapter => {
      builtWith.push(o.token);
      return {
        async *sendMessage() {
          if (o.token !== OLD) { yield ok; return; }
          if (oldCalls++ === 1) await gate;
          yield err401;
        },
      };
    };
    const adapter = withAuthRefresh(oauthOpts, build, refresher);
    const a = collect(adapter);
    const b = collect(adapter);
    expect(await a).toEqual([ok]);
    release();
    expect(await b).toEqual([ok]);
    expect(refresher.refresh).toHaveBeenCalledTimes(1);
    expect(builtWith).toEqual([OLD, NEW, NEW]);
  });

  it('does not retry non-401 errors', async () => {
    const e500: HarnessEvent = { type: 'error', message: 'x request failed with status 500', retryable: true };
    const { build, builtWith } = tokenAdapter(() => [e500]);
    expect(await collect(withAuthRefresh(oauthOpts, build, okRefresher))).toEqual([e500]);
    expect(builtWith).toEqual([OLD]);
  });
});

describe('createAppTokenRefresher', () => {
  const response = (status: number, body: unknown) => ({ status, json: async () => body }) as unknown as Response;

  it('sends sha256 of the rejected token, never the raw token', async () => {
    const fetchFn = vi.fn(async () => response(200, { token: NEW }));
    const onNewToken = vi.fn();
    const r = createAppTokenRefresher({ appBaseUrl: 'http://app', agentToken: 'agt', fetchFn, onNewToken });
    expect(await r.refresh('claude', OLD)).toBe(NEW);
    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('http://app/api/agent/llm-token/refresh');
    expect((init.headers as Record<string, string>)['X-Agent-Token']).toBe('agt');
    const body = JSON.parse(init.body as string) as { provider: string; rejectedTokenSha256: string };
    expect(body.provider).toBe('claude');
    expect(body.rejectedTokenSha256).toMatch(/^[0-9a-f]{64}$/);
    expect(init.body as string).not.toContain(OLD);
    expect(onNewToken).toHaveBeenCalledWith(NEW);
  });

  it('throws the server detail on non-200 without any token', async () => {
    const fetchFn = vi.fn(async () => response(503, { detail: 'needs reconnecting.' }));
    const r = createAppTokenRefresher({ appBaseUrl: 'http://app', agentToken: 'agt', fetchFn });
    await expect(r.refresh('codex', OLD)).rejects.toThrow(/503.*needs reconnecting\./);
  });

  it('passes an abort signal and surfaces a fetch failure/timeout without a token', async () => {
    const fetchFn = vi.fn(async () => { throw new DOMException('timeout', 'TimeoutError'); });
    const r = createAppTokenRefresher({ appBaseUrl: 'http://app', agentToken: 'agt', fetchFn });
    await expect(r.refresh('claude', OLD)).rejects.toThrow(/failed or timed out/);
    const init = (fetchFn.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it('coalesces three concurrent refreshes into one fetch', async () => {
    const fetchFn = vi.fn(async () => response(200, { token: NEW }));
    const r = createAppTokenRefresher({ appBaseUrl: 'http://app', agentToken: 'agt', fetchFn });
    const all = await Promise.all([r.refresh('claude', OLD), r.refresh('claude', OLD), r.refresh('claude', OLD)]);
    expect(all).toEqual([NEW, NEW, NEW]);
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });
});

describe('createRefreshingAdapterFactory', () => {
  it('falls back to createProviderAdapter when env is missing', () => {
    expect(createRefreshingAdapterFactory({})).toBe(createProviderAdapter);
    expect(createRefreshingAdapterFactory({ AGENT_API_TOKEN: 'a' })).toBe(createProviderAdapter);
    expect(createRefreshingAdapterFactory({ TRUTHCV_MCP_URL: 'http://app/mcp' })).toBe(createProviderAdapter);
  });

  it('returns a distinct wrapping factory when env is present', () => {
    const factory = createRefreshingAdapterFactory({ AGENT_API_TOKEN: 'a', TRUTHCV_MCP_URL: 'http://app/mcp/' });
    expect(factory).not.toBe(createProviderAdapter);
    expect(typeof factory({ ...oauthOpts, authType: 'api_key' }).sendMessage).toBe('function');
  });
});
