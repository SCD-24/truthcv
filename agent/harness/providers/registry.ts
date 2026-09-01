/**
 * Registry that builds the right provider adapter from a small, flat set
 * of options, keeping wire selection and auth routing in one place.
 */

import { createAnthropicMessagesAdapter } from './anthropicMessages.js';
import { createOpenAiChatCompletionsAdapter } from './openaiChatCompletions.js';
import { createOpenAiResponsesAdapter } from './openaiResponses.js';
import type { ProviderAdapter } from './types.js';

/** Known logical providers the harness can target. */
export type Provider = 'claude' | 'codex' | 'openrouter' | 'ollama';

/** The wire protocol a provider speaks.
 *
 * - `anthropic-messages` — Anthropic's /v1/messages API (also via OpenRouter).
 * - `openai-chat-completions` — OpenAI's /chat/completions API.
 * - `openai-responses` — ChatGPT Codex subscription Responses API (streaming).
 */
export type Wire = 'anthropic-messages' | 'openai-chat-completions' | 'openai-responses';

/** How the supplied token should be presented to the provider. */
export type AuthType = 'oauth' | 'api_key' | 'url';

/** Flat options describing which adapter to build and how to auth it. */
export interface ProviderAdapterOptions {
  /** Logical provider being targeted. */
  provider: Provider;
  /** Wire protocol to speak. */
  wire: Wire;
  /** Model identifier to request. */
  model: string;
  /** Credential token (api key or OAuth token); empty when unauthenticated. */
  token: string;
  /** Base URL; may be empty to accept the provider default. */
  baseUrl: string;
  /** Optional context window forwarded to servers that need it stated. */
  contextWindow?: number;
  /** How to present the token; defaults to api-key routing when absent. */
  authType?: AuthType;
  /**
   * Whether Anthropic prompt-cache `cache_control` breakpoints are placed on
   * the wire. Defaults to true when undefined; false disables caching entirely.
   * Anthropic-only — ignored by the OpenAI-wire adapter, which relies on
   * automatic prefix caching.
   */
  promptCache?: boolean;
}

/** Default base URLs for OpenAI-wire providers when none is supplied. */
const OPENAI_WIRE_DEFAULTS: Partial<Record<Provider, string>> = {
  codex: 'https://api.openai.com/v1',
  openrouter: 'https://openrouter.ai/api/v1',
};

/** Build an Anthropic Messages adapter, routing OAuth vs api-key auth. */
function buildAnthropic(opts: ProviderAdapterOptions): ProviderAdapter {
  const useOauth = opts.authType === 'oauth';
  return createAnthropicMessagesAdapter({
    model: opts.model,
    baseUrl: opts.baseUrl || undefined,
    ...(useOauth ? { oauthToken: opts.token } : { apiKey: opts.token }),
    ...(opts.promptCache !== undefined ? { promptCache: opts.promptCache } : {}),
  });
}

/** Build an OpenAI Chat Completions adapter with a resolved base URL. */
function buildOpenAi(opts: ProviderAdapterOptions): ProviderAdapter {
  const baseUrl = opts.baseUrl || OPENAI_WIRE_DEFAULTS[opts.provider] || '';
  return createOpenAiChatCompletionsAdapter({
    model: opts.model,
    baseUrl,
    apiKey: opts.token,
    contextWindow: opts.contextWindow,
  });
}

/** Build an OpenAI Responses adapter (ChatGPT Codex subscription wire). */
function buildOpenAiResponses(opts: ProviderAdapterOptions): ProviderAdapter {
  return createOpenAiResponsesAdapter({
    token: opts.token,
    model: opts.model,
    baseUrl: opts.baseUrl || undefined,
  });
}

/** Construct the provider adapter selected by the given options.
 *
 * Dispatches over the `wire` field explicitly — unknown wires throw so a
 * misconfigured env cannot silently fall through to the wrong adapter and
 * send an OAuth token as an API key.
 */
export function createProviderAdapter(opts: ProviderAdapterOptions): ProviderAdapter {
  switch (opts.wire) {
    case 'anthropic-messages':
      return buildAnthropic(opts);
    case 'openai-chat-completions':
      return buildOpenAi(opts);
    case 'openai-responses':
      return buildOpenAiResponses(opts);
    default:
      throw new Error(`Unrecognised wire '${String(opts.wire)}'`);
  }
}
