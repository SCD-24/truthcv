import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_FALLBACK_CONTEXT_WINDOW } from '../compaction.js';
import { discoverContextWindow } from '../contextWindow.js';

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe('discoverContextWindow', () => {
  it('openrouter: reads context_length for the matching model id', async () => {
    const fetchFn = vi.fn(async () =>
      jsonResponse(200, { data: [{ id: 'other/model', context_length: 1 }, { id: 'x/y', context_length: 131072 }] }),
    );
    const result = await discoverContextWindow(
      { provider: 'openrouter', wire: 'openai-chat-completions', model: 'x/y', baseUrl: '', token: 'secret-token' },
      fetchFn,
    );
    expect(result).toEqual({ window: 131072, source: 'openrouter' });
    expect(result.source).not.toContain('secret-token');
  });

  it('openrouter: falls back to top_provider.context_length when context_length is absent', async () => {
    const fetchFn = vi.fn(async () =>
      jsonResponse(200, { data: [{ id: 'x/y', top_provider: { context_length: 64000 } }] }),
    );
    const result = await discoverContextWindow(
      { provider: 'openrouter', wire: 'openai-chat-completions', model: 'x/y', baseUrl: '', token: '' },
      fetchFn,
    );
    expect(result).toEqual({ window: 64000, source: 'openrouter' });
  });

  it('openrouter: model not found falls back', async () => {
    const fetchFn = vi.fn(async () => jsonResponse(200, { data: [{ id: 'other', context_length: 1000 }] }));
    const result = await discoverContextWindow(
      { provider: 'openrouter', wire: 'openai-chat-completions', model: 'x/y', baseUrl: '', token: '' },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).toContain('fallback');
    expect(result.source).toContain('not found');
  });

  it('openrouter: 401 response falls back', async () => {
    const fetchFn = vi.fn(async () => jsonResponse(401, { error: 'unauthorized' }));
    const result = await discoverContextWindow(
      { provider: 'openrouter', wire: 'openai-chat-completions', model: 'x/y', baseUrl: '', token: 'secret-token' },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).toContain('401');
    expect(result.source).not.toContain('secret-token');
  });

  it('openrouter: garbage context_length falls back', async () => {
    const fetchFn = vi.fn(async () => jsonResponse(200, { data: [{ id: 'x/y', context_length: 'lots' }] }));
    const result = await discoverContextWindow(
      { provider: 'openrouter', wire: 'openai-chat-completions', model: 'x/y', baseUrl: '', token: '' },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).toContain('fallback');
  });

  it('openrouter: timeout falls back', async () => {
    const fetchFn = vi.fn(async () => {
      const err = new Error('The operation was aborted');
      err.name = 'TimeoutError';
      throw err;
    });
    const result = await discoverContextWindow(
      { provider: 'openrouter', wire: 'openai-chat-completions', model: 'x/y', baseUrl: '', token: '' },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).toContain('timed out');
  });

  it('claude: reads max_input_tokens using x-api-key for api_key authType', async () => {
    let capturedHeaders: Record<string, string> | undefined;
    const fetchFn = vi.fn<typeof fetch>(async (_input, init) => {
      capturedHeaders = init?.headers as Record<string, string>;
      return jsonResponse(200, { max_input_tokens: 200000 });
    });
    const result = await discoverContextWindow(
      {
        provider: 'claude',
        wire: 'anthropic-messages',
        model: 'claude-x',
        baseUrl: '',
        token: 'secret-token',
        authType: 'api_key',
      },
      fetchFn,
    );
    expect(result).toEqual({ window: 200000, source: 'anthropic' });
    expect(capturedHeaders?.['x-api-key']).toBe('secret-token');
    expect(capturedHeaders?.['authorization']).toBeUndefined();
    expect(capturedHeaders?.['anthropic-version']).toBeTruthy();
  });

  it('claude: uses Bearer auth for non-api_key authType', async () => {
    let capturedHeaders: Record<string, string> | undefined;
    const fetchFn = vi.fn<typeof fetch>(async (_input, init) => {
      capturedHeaders = init?.headers as Record<string, string>;
      return jsonResponse(200, { max_input_tokens: 100000 });
    });
    await discoverContextWindow(
      { provider: 'claude', wire: 'anthropic-messages', model: 'claude-x', baseUrl: '', token: 'oauth-token', authType: 'oauth' },
      fetchFn,
    );
    expect(capturedHeaders?.['authorization']).toBe('Bearer oauth-token');
    expect(capturedHeaders?.['x-api-key']).toBeUndefined();
  });

  it('claude: requests /v1/models/{model} against the default base URL', async () => {
    const fetchFn = vi.fn<typeof fetch>(async () => jsonResponse(200, { max_input_tokens: 200000 }));
    await discoverContextWindow(
      { provider: 'claude', wire: 'anthropic-messages', model: 'claude-x', baseUrl: '', token: '' },
      fetchFn,
    );
    const [url] = fetchFn.mock.calls[0];
    expect(String(url)).toBe('https://api.anthropic.com/v1/models/claude-x');
  });

  it('claude: strips a trailing slash from a custom base URL before appending /v1/models/{model}', async () => {
    const fetchFn = vi.fn<typeof fetch>(async () => jsonResponse(200, { max_input_tokens: 200000 }));
    await discoverContextWindow(
      { provider: 'claude', wire: 'anthropic-messages', model: 'claude-x', baseUrl: 'https://proxy.example/', token: '' },
      fetchFn,
    );
    const [url] = fetchFn.mock.calls[0];
    expect(String(url)).toBe('https://proxy.example/v1/models/claude-x');
  });

  it('claude: 401 falls back without leaking the token', async () => {
    const fetchFn = vi.fn(async () => jsonResponse(401, { error: 'unauthorized' }));
    const result = await discoverContextWindow(
      { provider: 'claude', wire: 'anthropic-messages', model: 'claude-x', baseUrl: '', token: 'secret-token', authType: 'api_key' },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).toContain('401');
    expect(result.source).not.toContain('secret-token');
  });

  it('ollama: reads the first *.context_length key from model_info', async () => {
    const fetchFn = vi.fn<typeof fetch>(async () => jsonResponse(200, { model_info: { 'llama.context_length': 8192 } }));
    const result = await discoverContextWindow(
      { provider: 'ollama', wire: 'openai-chat-completions', model: 'llama3', baseUrl: 'http://localhost:11434/v1', token: '' },
      fetchFn,
    );
    expect(result).toEqual({ window: 8192, source: 'ollama' });
    const [url] = fetchFn.mock.calls[0];
    expect(String(url)).toBe('http://localhost:11434/api/show');
  });

  it('ollama: garbage value falls back', async () => {
    const fetchFn = vi.fn(async () => jsonResponse(200, { model_info: { 'llama.context_length': 'many' } }));
    const result = await discoverContextWindow(
      { provider: 'ollama', wire: 'openai-chat-completions', model: 'llama3', baseUrl: 'http://localhost:11434', token: '' },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
  });

  it('codex: reads context_window for the matching model slug from the models catalog', async () => {
    const fetchFn = vi.fn(async () =>
      jsonResponse(200, { models: [{ slug: 'gpt-5-codex', context_window: 272000, max_context_window: 400000 }] }),
    );
    const result = await discoverContextWindow(
      { provider: 'codex', wire: 'openai-responses', model: 'gpt-5-codex', baseUrl: '', token: 'secret-token' },
      fetchFn,
    );
    expect(result).toEqual({ window: 272000, source: 'codex' });
    const url = (fetchFn.mock.calls[0] as unknown[])[0];
    expect(String(url)).toContain('/models?client_version=');
  });

  it('codex: model not in the catalog falls back', async () => {
    const fetchFn = vi.fn(async () => jsonResponse(200, { models: [{ slug: 'other', context_window: 1000 }] }));
    const result = await discoverContextWindow(
      { provider: 'codex', wire: 'openai-responses', model: 'gpt-5-codex', baseUrl: '', token: '' },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).toContain('not found');
  });

  it('codex: non-2xx response falls back', async () => {
    const fetchFn = vi.fn(async () => jsonResponse(500, { error: 'boom' }));
    const result = await discoverContextWindow(
      { provider: 'codex', wire: 'openai-responses', model: 'gpt-5-codex', baseUrl: '', token: '' },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).toContain('500');
  });

  it('codex: sends chatgpt-account-id decoded from the token', async () => {
    const payload = Buffer.from(JSON.stringify({ 'https://api.openai.com/auth': { chatgpt_account_id: 'acct-1' } })).toString('base64url');
    const token = `header.${payload}.sig`;
    let capturedHeaders: Record<string, string> | undefined;
    const fetchFn = vi.fn<typeof fetch>(async (_input, init) => {
      capturedHeaders = init?.headers as Record<string, string>;
      return jsonResponse(200, { models: [{ slug: 'gpt-5-codex', context_window: 272000 }] });
    });
    await discoverContextWindow(
      { provider: 'codex', wire: 'openai-responses', model: 'gpt-5-codex', baseUrl: '', token },
      fetchFn,
    );
    expect(capturedHeaders?.['chatgpt-account-id']).toBe('acct-1');
  });

  it('codex: token is redacted in the fallback source when the request throws', async () => {
    const token = 'secret-codex-token';
    const fetchFn = vi.fn(async () => {
      throw new Error(`failed for ${token}`);
    });
    const result = await discoverContextWindow(
      { provider: 'codex', wire: 'openai-responses', model: 'gpt-5-codex', baseUrl: '', token },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).not.toContain(token);
  });

  it('codex: max_context_window is ignored when context_window is absent', async () => {
    const fetchFn = vi.fn(async () =>
      jsonResponse(200, { models: [{ slug: 'gpt-5-codex', max_context_window: 400000 }] }),
    );
    const result = await discoverContextWindow(
      { provider: 'codex', wire: 'openai-responses', model: 'gpt-5-codex', baseUrl: '', token: '' },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).toContain('fallback');
  });

  it('codex: api_key authType uses the OpenAI /v1/models path and falls back when no context field is present', async () => {
    const fetchFn = vi.fn(async () => jsonResponse(200, { id: 'gpt-5-codex' }));
    const result = await discoverContextWindow(
      {
        provider: 'codex',
        wire: 'openai-responses',
        model: 'gpt-5-codex',
        baseUrl: '',
        token: 'sk-test',
        authType: 'api_key',
      },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).toContain('no context window');
    const url = (fetchFn.mock.calls[0] as unknown[])[0];
    expect(String(url)).toBe('https://api.openai.com/v1/models/gpt-5-codex');
  });

  it('codex: openai-chat-completions wire with empty baseUrl uses api.openai.com, not the ChatGPT backend', async () => {
    const fetchFn = vi.fn(async () => jsonResponse(200, { id: 'gpt-5-codex' }));
    const result = await discoverContextWindow(
      { provider: 'codex', wire: 'openai-chat-completions', model: 'gpt-5-codex', baseUrl: '', token: '' },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).toContain('no context window');
    const url = (fetchFn.mock.calls[0] as unknown[])[0];
    expect(String(url)).toBe('https://api.openai.com/v1/models/gpt-5-codex');
  });

  it('dispatches on provider before wire: ollama on the anthropic-messages wire still uses /api/show', async () => {
    const fetchFn = vi.fn(async (_url: RequestInfo | URL) => jsonResponse(200, { model_info: { 'llama.context_length': 8192 } }));
    const result = await discoverContextWindow(
      { provider: 'ollama', wire: 'anthropic-messages', model: 'llama3', baseUrl: 'http://localhost:11434', token: '' },
      fetchFn,
    );
    expect(result).toEqual({ window: 8192, source: 'ollama' });
    expect(String(fetchFn.mock.calls[0][0])).toBe('http://localhost:11434/api/show');
  });

  it('codex: redacts the token from a JSON-parse failure message', async () => {
    const token = 'secret-codex-token';
    const badJson = { ok: true, status: 200, json: async () => { throw new Error(`invalid JSON: ${token}`); } } as unknown as Response;
    const fetchFn = vi.fn(async () => badJson);
    const result = await discoverContextWindow(
      { provider: 'codex', wire: 'openai-responses', model: 'gpt-5-codex', baseUrl: '', token },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).not.toContain(token);
    expect(result.source).toContain('[redacted]');
  });

  it('network error falls back rather than throwing', async () => {
    const fetchFn = vi.fn(async () => {
      throw new Error('ECONNREFUSED');
    });
    const result = await discoverContextWindow(
      { provider: 'ollama', wire: 'openai-chat-completions', model: 'llama3', baseUrl: 'http://localhost:11434', token: '' },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).toContain('ECONNREFUSED');
  });

  it('network error message redacts the token', async () => {
    const token = 'super-secret-token';
    const fetchFn = vi.fn(async () => {
      throw new Error(`connection failed for ${token}`);
    });
    const result = await discoverContextWindow(
      { provider: 'ollama', wire: 'openai-chat-completions', model: 'llama3', baseUrl: 'http://localhost:11434', token },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).not.toContain(token);
    expect(result.source).toContain('[redacted]');
  });

  it('claude on the openai-responses wire still uses the Anthropic discoverer', async () => {
    const fetchFn = vi.fn<typeof fetch>(async () => jsonResponse(200, { max_input_tokens: 200000 }));
    const result = await discoverContextWindow(
      { provider: 'claude', wire: 'openai-responses', model: 'x', baseUrl: '', token: '' },
      fetchFn,
    );
    expect(result).toEqual({ window: 200000, source: 'anthropic' });
  });

  it('malformed (non-object) response body falls back instead of throwing', async () => {
    const fetchFn = vi.fn(async () => jsonResponse(200, null));
    const result = await discoverContextWindow(
      { provider: 'claude', wire: 'anthropic-messages', model: 'claude-x', baseUrl: '', token: '' },
      fetchFn,
    );
    expect(result.window).toBe(DEFAULT_FALLBACK_CONTEXT_WINDOW);
    expect(result.source).toContain('fallback');
  });
});
