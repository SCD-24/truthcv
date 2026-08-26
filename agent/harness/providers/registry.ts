/**
 * Registry that builds the right provider adapter from a small, flat set
 * of options, keeping wire selection and auth routing in one place.
 */

import { createAnthropicMessagesAdapter } from './anthropicMessages.js';
import { createOpenAiChatCompletionsAdapter } from './openaiChatCompletions.js';
import type { ProviderAdapter } from './types.js';

/** Known logical providers the harness can target. */
export type Provider = 'claude' | 'codex' | 'openrouter' | 'ollama';

/** The wire protocol a provider speaks. */
export type Wire = 'anthropic-messages' | 'openai-chat-completions';

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

/** Construct the provider adapter selected by the given options. */
export function createProviderAdapter(opts: ProviderAdapterOptions): ProviderAdapter {
  return opts.wire === 'anthropic-messages' ? buildAnthropic(opts) : buildOpenAi(opts);
}
