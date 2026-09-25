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
import type { AuthType, Provider, Wire } from './providers/registry.js';

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
    return fallback(`openrouter response was not valid JSON (${errorMessage(err)})`);
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
    return fallback(`anthropic response was not valid JSON (${errorMessage(err)})`);
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
    return fallback(`ollama response was not valid JSON (${errorMessage(err)})`);
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

/**
 * Discover a model's input context window from its provider.
 *
 * Never throws: every failure path resolves to `{ window:
 * DEFAULT_FALLBACK_CONTEXT_WINDOW, source: 'fallback: <reason>' }`, and no
 * `source` string ever includes the credential token. `codex`,
 * `openai-responses` and any other unrecognised combination have no
 * discovery endpoint and fall back immediately.
 */
export async function discoverContextWindow(
  opts: DiscoverContextWindowOptions,
  fetchFn: FetchFn = fetch,
): Promise<DiscoveredContextWindow> {
  try {
    if (opts.wire === 'openai-responses') return fallback(`no discovery endpoint for wire '${opts.wire}'`);
    if (opts.provider === 'openrouter') return await discoverOpenRouter(opts, fetchFn);
    if (opts.provider === 'claude' || opts.wire === 'anthropic-messages') return await discoverAnthropic(opts, fetchFn);
    if (opts.provider === 'ollama') return await discoverOllama(opts, fetchFn);
    return fallback(`no discovery endpoint for provider '${opts.provider}'`);
  } catch (err) {
    return fallback(`unexpected error (${errorMessage(err, opts.token)})`);
  }
}
