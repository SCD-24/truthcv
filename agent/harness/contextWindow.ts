/**
 * Discovers a model's input context window directly from its provider,
 * replacing the old operator-stated `AGENT_CONTEXT_WINDOW` env/flag.
 *
 * Every provider path is best-effort: any failure — network error, timeout,
 * non-2xx, missing model, or a reported value that is not a positive integer
 * — resolves to the same conservative fallback rather than throwing, so a
 * flaky or unsupported provider never blocks a run from starting.
 */

import { DEFAULT_FALLBACK_CONTEXT_WINDOW } from './compaction.js';
import { accountIdFromToken } from './providers/openaiResponses.js';
import type { AuthType, Provider, Wire } from './providers/registry.js';

/**
 * Client version sent to the Codex `/models` catalog. The backend may filter
 * which models it lists by client version, so a model missing from the
 * response just falls back — it does not mean discovery is broken.
 */
export const CODEX_MODELS_CLIENT_VERSION = '0.50.0';

/** Time budget for a single discovery call before it is treated as failed. */
export const DISCOVERY_TIMEOUT_MS = 5000;

/** Inputs needed to discover one adapter's context window. */
export interface DiscoverContextWindowOptions {
  /** Logical provider being targeted. */
  provider: Provider;
  /** Wire protocol the provider speaks. */
  wire: Wire;
  /** Model identifier to look up. */
  model: string;
  /** Base URL override; empty to accept the provider default. */
  baseUrl: string;
  /** Credential token; empty when unauthenticated. */
  token: string;
  /** How the token should be presented. */
  authType?: AuthType;
}

/** Result of a discovery attempt. */
export interface DiscoveredContextWindow {
  /** The model's input context window in tokens. */
  window: number;
  /** Where the number came from: a provider name, or `fallback: <reason>`. */
  source: string;
}

/** Signature a fetch replacement must satisfy (matches the global `fetch`). */
type FetchFn = typeof fetch;

/** Build the fallback result, never including the token in `source`. */
function fallback(reason: string): DiscoveredContextWindow {
  return { window: DEFAULT_FALLBACK_CONTEXT_WINDOW, source: `fallback: ${reason}` };
}

/** True when `value` is a usable context-window number. */
function isValidWindow(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0;
}

/** True when `value` is a non-null, non-array plain object (a usable JSON body). */
function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Discover the context window for OpenRouter via its `/models` listing. */
async function discoverOpenRouter(
  opts: DiscoverContextWindowOptions,
  fetchFn: FetchFn,
): Promise<DiscoveredContextWindow> {
  const base = opts.baseUrl || 'https://openrouter.ai/api/v1';
  let response: Response;
  try {
    response = await fetchFn(`${base}/models`, {
      headers: opts.token ? { authorization: `Bearer ${opts.token}` } : {},
      signal: AbortSignal.timeout(DISCOVERY_TIMEOUT_MS),
    });
  } catch (err) {
    return fallback(`openrouter request failed (${errorMessage(err, opts.token)})`);
  }
  if (!response.ok) return fallback(`openrouter responded with status ${response.status}`);
  let body: { data?: Array<{ id?: string; context_length?: unknown; top_provider?: { context_length?: unknown } }> };
  try {
    const parsed: unknown = await response.json();
    if (!isPlainObject(parsed)) return fallback('malformed response');
    body = parsed as typeof body;
  } catch (err) {
    return fallback(`openrouter response was not valid JSON (${errorMessage(err, opts.token)})`);
  }
  const entry = body.data?.find((m) => m.id === opts.model);
  if (!entry) return fallback(`model '${opts.model}' not found in openrouter model list`);
  const window = entry.context_length ?? entry.top_provider?.context_length;
  if (!isValidWindow(window)) return fallback(`openrouter reported no usable context_length for '${opts.model}'`);
  return { window, source: 'openrouter' };
}

/** Build the Anthropic Models auth header for the configured authType. */
function anthropicAuthHeaders(opts: DiscoverContextWindowOptions): Record<string, string> {
  if (!opts.token) return {};
  return opts.authType === 'api_key' ? { 'x-api-key': opts.token } : { authorization: `Bearer ${opts.token}` };
}

/** Discover the context window for the Anthropic Messages wire. */
async function discoverAnthropic(
  opts: DiscoverContextWindowOptions,
  fetchFn: FetchFn,
): Promise<DiscoveredContextWindow> {
  // Same base-URL contract as the Messages adapter, which appends `/v1/messages`
  // to a root URL — so the root here must get `/v1` appended too.
  const base = (opts.baseUrl || 'https://api.anthropic.com').replace(/\/+$/, '');
  let response: Response;
  try {
    response = await fetchFn(`${base}/v1/models/${encodeURIComponent(opts.model)}`, {
      headers: { ...anthropicAuthHeaders(opts), 'anthropic-version': '2023-06-01' },
      signal: AbortSignal.timeout(DISCOVERY_TIMEOUT_MS),
    });
  } catch (err) {
    return fallback(`anthropic request failed (${errorMessage(err, opts.token)})`);
  }
  if (!response.ok) return fallback(`anthropic responded with status ${response.status}`);
  let body: { max_input_tokens?: unknown };
  try {
    const parsed: unknown = await response.json();
    if (!isPlainObject(parsed)) return fallback('malformed response');
    body = parsed as typeof body;
  } catch (err) {
    return fallback(`anthropic response was not valid JSON (${errorMessage(err, opts.token)})`);
  }
  if (!isValidWindow(body.max_input_tokens))
    return fallback(`anthropic reported no usable max_input_tokens for '${opts.model}'`);
  return { window: body.max_input_tokens, source: 'anthropic' };
}

/** Strip a trailing `/v1` (with or without slash) from a base URL, for Ollama. */
function stripTrailingV1(baseUrl: string): string {
  return baseUrl.replace(/\/v1\/?$/, '');
}

/** First `model_info` value keyed by a name ending in `.context_length`. */
function ollamaContextLength(modelInfo: Record<string, unknown> | undefined): unknown {
  if (!modelInfo) return undefined;
  const key = Object.keys(modelInfo).find((k) => k.endsWith('.context_length'));
  return key ? modelInfo[key] : undefined;
}

/** Discover the context window from a local Ollama server's `/api/show`. */
async function discoverOllama(
  opts: DiscoverContextWindowOptions,
  fetchFn: FetchFn,
): Promise<DiscoveredContextWindow> {
  const base = stripTrailingV1(opts.baseUrl || '');
  if (!base) return fallback('ollama has no baseUrl configured');
  let response: Response;
  try {
    response = await fetchFn(`${base}/api/show`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model: opts.model }),
      signal: AbortSignal.timeout(DISCOVERY_TIMEOUT_MS),
    });
  } catch (err) {
    return fallback(`ollama request failed (${errorMessage(err, opts.token)})`);
  }
  if (!response.ok) return fallback(`ollama responded with status ${response.status}`);
  let body: { model_info?: Record<string, unknown> };
  try {
    const parsed: unknown = await response.json();
    if (!isPlainObject(parsed)) return fallback('malformed response');
    body = parsed as typeof body;
  } catch (err) {
    return fallback(`ollama response was not valid JSON (${errorMessage(err, opts.token)})`);
  }
  const window = ollamaContextLength(body.model_info);
  if (!isValidWindow(window)) return fallback(`ollama reported no usable context_length for '${opts.model}'`);
  return { window, source: 'ollama' };
}

/** Render an unknown thrown value (network error, abort) as short text, with any token redacted. */
function errorMessage(err: unknown, token?: string): string {
  const message = err instanceof Error ? (err.name === 'TimeoutError' ? 'timed out' : err.message) : String(err);
  return token ? message.split(token).join('[redacted]') : message;
}

/** True when the Codex base URL targets OpenAI's own API rather than the ChatGPT backend. */
function isOpenAiApiHost(base: string): boolean {
  try {
    return new URL(base).hostname === 'api.openai.com';
  } catch {
    return false;
  }
}

/** Discover the context window from OpenAI's `/v1/models/{model}` (api-key Codex path). */
async function discoverOpenAiModels(
  opts: DiscoverContextWindowOptions,
  base: string,
  fetchFn: FetchFn,
): Promise<DiscoveredContextWindow> {
  let response: Response;
  try {
    response = await fetchFn(`${base}/models/${encodeURIComponent(opts.model)}`, {
      headers: opts.token ? { authorization: `Bearer ${opts.token}` } : {},
      signal: AbortSignal.timeout(DISCOVERY_TIMEOUT_MS),
    });
  } catch (err) {
    return fallback(`openai request failed (${errorMessage(err, opts.token)})`);
  }
  if (!response.ok) return fallback(`openai responded with status ${response.status}`);
  let body: { context_window?: unknown; context_length?: unknown };
  try {
    const parsed: unknown = await response.json();
    if (!isPlainObject(parsed)) return fallback('malformed response');
    body = parsed as typeof body;
  } catch (err) {
    return fallback(`openai response was not valid JSON (${errorMessage(err, opts.token)})`);
  }
  // OpenAI's /v1/models endpoint generally does not report a context length at
  // all, so a missing field here is the common case, not an error.
  const window = body.context_window ?? body.context_length;
  if (!isValidWindow(window)) return fallback(`openai models endpoint reports no context window for '${opts.model}'`);
  return { window, source: 'openai' };
}

/** Build auth headers for the Codex `/models` catalog. */
function codexAuthHeaders(token: string): Record<string, string> {
  const headers: Record<string, string> = { authorization: `Bearer ${token}`, originator: 'truthcv' };
  const accountId = accountIdFromToken(token);
  if (accountId) headers['chatgpt-account-id'] = accountId;
  return headers;
}

/**
 * Picks the Codex discovery route and base URL. The ChatGPT catalog is only
 * used for the `openai-responses` wire, non-api_key auth, and a base that
 * isn't already OpenAI's own API host; every other case (including the
 * `openai-chat-completions` wire, whose adapter default base is
 * `api.openai.com/v1`) talks to OpenAI's `/v1/models/{model}` endpoint.
 */
function codexRoute(opts: DiscoverContextWindowOptions): { useChatGpt: boolean; base: string } {
  if (opts.wire === 'openai-responses' && opts.authType !== 'api_key') {
    const base = (opts.baseUrl || 'https://chatgpt.com/backend-api/codex').replace(/\/+$/, '');
    if (!isOpenAiApiHost(base)) return { useChatGpt: true, base };
  }
  return { useChatGpt: false, base: (opts.baseUrl || 'https://api.openai.com/v1').replace(/\/+$/, '') };
}

/**
 * Discovers Codex's context window. For the `openai-responses` wire with a
 * non-api_key auth type and a base that is not OpenAI's own API host, this
 * queries the ChatGPT backend's Codex model catalog; otherwise (including the
 * `openai-chat-completions` wire, or an api_key auth type, or an explicit
 * `api.openai.com` base) it falls back to OpenAI's `/v1/models/{model}`.
 */
async function discoverCodex(
  opts: DiscoverContextWindowOptions,
  fetchFn: FetchFn,
): Promise<DiscoveredContextWindow> {
  const { useChatGpt, base } = codexRoute(opts);
  if (!useChatGpt) return discoverOpenAiModels(opts, base, fetchFn);
  let response: Response;
  try {
    response = await fetchFn(`${base}/models?client_version=${CODEX_MODELS_CLIENT_VERSION}`, {
      headers: codexAuthHeaders(opts.token),
      signal: AbortSignal.timeout(DISCOVERY_TIMEOUT_MS),
    });
  } catch (err) {
    return fallback(`codex request failed (${errorMessage(err, opts.token)})`);
  }
  if (!response.ok) return fallback(`codex responded with status ${response.status}`);
  let body: { models?: Array<{ slug?: string; context_window?: unknown }> };
  try {
    const parsed: unknown = await response.json();
    if (!isPlainObject(parsed)) return fallback('malformed response');
    body = parsed as typeof body;
  } catch (err) {
    return fallback(`codex response was not valid JSON (${errorMessage(err, opts.token)})`);
  }
  const entry = body.models?.find((m) => m.slug === opts.model);
  if (!entry) return fallback(`model '${opts.model}' not found in codex model list`);
  if (!isValidWindow(entry.context_window))
    return fallback(`codex reported no usable context_window for '${opts.model}'`);
  return { window: entry.context_window, source: 'codex' };
}

/**
 * Discover a model's input context window from its provider.
 *
 * Never throws: every failure path resolves to `{ window:
 * DEFAULT_FALLBACK_CONTEXT_WINDOW, source: 'fallback: <reason>' }`, and no
 * `source` string ever includes the credential token. Codex is discovered
 * via its models catalog (or OpenAI's `/v1/models` when using an API key);
 * any other unrecognised provider has no discovery endpoint and falls back
 * immediately.
 */
export async function discoverContextWindow(
  opts: DiscoverContextWindowOptions,
  fetchFn: FetchFn = fetch,
): Promise<DiscoveredContextWindow> {
  try {
    if (opts.provider === 'openrouter') return await discoverOpenRouter(opts, fetchFn);
    if (opts.provider === 'claude') return await discoverAnthropic(opts, fetchFn);
    if (opts.provider === 'ollama') return await discoverOllama(opts, fetchFn);
    if (opts.provider === 'codex') return await discoverCodex(opts, fetchFn);
    // Provider first, wire last: an unrecognised provider on the Anthropic
    // wire still speaks the Anthropic Models API.
    if (opts.wire === 'anthropic-messages') return await discoverAnthropic(opts, fetchFn);
    return fallback(`no discovery endpoint for provider '${opts.provider}'`);
  } catch (err) {
    return fallback(`unexpected error (${errorMessage(err, opts.token)})`);
  }
}
