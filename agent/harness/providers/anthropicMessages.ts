/**
 * Adapter translating the normalised harness types to and from the
 * Anthropic Messages API (non-streaming, single JSON response).
 */

import type {
  ConversationMessage,
  HarnessEvent,
  ModelRequest,
  ProviderAdapter,
  StopReason,
  ToolCall,
  ToolDefinition,
} from './types.js';

import { networkErrorEvent, providerErrorEvent, readBody, retryAfterMsFrom } from './errors.js';

/** Options for constructing an Anthropic Messages adapter. */
export interface AnthropicMessagesOptions {
  /** API key sent as the `x-api-key` header. */
  apiKey?: string;
  /** OAuth token sent as a Bearer `authorization` header. */
  oauthToken?: string;
  /** Override for the API base URL. */
  baseUrl?: string;
  /** Model identifier to request. */
  model: string;
}

/** HTTP statuses worth retrying. */
const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 504]);

/**
 * Preamble a Claude subscription (OAuth) token requires as its FIRST system
 * block. Without it the Messages API rejects the request — as a 429
 * `rate_limit_error` whose message is the bare string "Error", which reads
 * exactly like an exhausted quota and is not one: the same token, in the same
 * second, answers 200 when the block is present.
 *
 * Must stay byte-identical to CLAUDE_CODE_PREAMBLE in connections/auth/claude.py,
 * which is what the app's own provider (providers/anthropic_provider.py
 * _system_param) sends. tests/test_anthropic_oauth_preamble.py pins the two
 * together.
 */
const CLAUDE_CODE_PREAMBLE = "You are Claude Code, Anthropic's official CLI for Claude.";

/** Whether these options authenticate with a subscription token rather than an
 * API key. The two need different headers AND a different system-prompt shape. */
function isOauth(opts: AnthropicMessagesOptions): boolean {
  return Boolean(opts.oauthToken);
}

/** Build the request headers, choosing api-key or OAuth auth. */
function buildHeaders(opts: AnthropicMessagesOptions): Record<string, string> {
  const headers: Record<string, string> = {
    'anthropic-version': '2023-06-01',
    'content-type': 'application/json',
  };
  if (isOauth(opts)) {
    headers['authorization'] = `Bearer ${opts.oauthToken}`;
    // Matches providers/anthropic_provider.py's default_headers. The preamble
    // is what the API actually gates on, but this is the shape the app already
    // sends successfully and the two should not diverge.
    headers['anthropic-beta'] = 'oauth-2025-04-20';
  } else if (opts.apiKey) {
    headers['x-api-key'] = opts.apiKey;
  }
  return headers;
}

/**
 * The `system` field: a plain string for an API key, and the preamble-first
 * block array a subscription token requires.
 *
 * An empty prompt contributes no block: the API rejects a text block whose
 * text is empty, and appending one would trade this bug for another.
 */
function buildSystem(systemPrompt: string, opts: AnthropicMessagesOptions): unknown {
  if (!isOauth(opts)) return systemPrompt;
  const blocks: unknown[] = [{ type: 'text', text: CLAUDE_CODE_PREAMBLE }];
  if (systemPrompt) blocks.push({ type: 'text', text: systemPrompt });
  return blocks;
}

/** Map one normalised message to an Anthropic role/content-block pair. */
function toAnthropicMessage(message: ConversationMessage): unknown {
  const role = message.role === 'assistant' ? 'assistant' : 'user';
  const blocks: unknown[] = [];
  if (message.content) blocks.push({ type: 'text', text: message.content });
  for (const call of message.toolCalls ?? [])
    blocks.push({ type: 'tool_use', id: call.id, name: call.name, input: call.arguments });
  for (const result of message.toolResults ?? [])
    blocks.push(toToolResultBlock(result.toolCallId, result.content, result.isError));
  return { role, content: blocks.length > 0 ? blocks : message.content };
}

/** Build an Anthropic `tool_result` content block. */
function toToolResultBlock(id: string, content: string, isError?: boolean): unknown {
  return { type: 'tool_result', tool_use_id: id, content, is_error: isError ?? false };
}

/** Map normalised tool definitions to Anthropic's tool shape. */
function toAnthropicTools(tools: ToolDefinition[]): unknown[] {
  return tools.map((tool) => ({
    name: tool.name,
    description: tool.description,
    input_schema: tool.inputSchema,
  }));
}

/** Assemble the full Anthropic request body from a ModelRequest. */
function buildBody(request: ModelRequest, opts: AnthropicMessagesOptions): unknown {
  return {
    model: opts.model,
    max_tokens: request.maxTokens ?? 4096,
    system: buildSystem(request.systemPrompt, opts),
    messages: request.messages.map(toAnthropicMessage),
    tools: toAnthropicTools(request.tools),
  };
}

/** Translate an Anthropic stop_reason to a normalised StopReason. */
function mapStopReason(reason: unknown): StopReason {
  if (reason === 'end_turn') return 'end';
  if (reason === 'tool_use') return 'toolCalls';
  if (reason === 'max_tokens') return 'length';
  return 'error';
}

/** Shape of the fields we read from an Anthropic response block. */
interface AnthropicBlock {
  type: string;
  text?: string;
  id?: string;
  name?: string;
  input?: Record<string, unknown>;
}

/** Convert a text/tool_use block into a HarnessEvent, or undefined. */
function blockToEvent(block: AnthropicBlock): HarnessEvent | undefined {
  if (block.type === 'text' && block.text !== undefined)
    return { type: 'text', delta: block.text };
  if (block.type === 'tool_use') {
    const toolCall: ToolCall = {
      id: block.id ?? '',
      name: block.name ?? '',
      arguments: block.input ?? {},
    };
    return { type: 'toolCall', toolCall };
  }
  return undefined;
}

/** Adapter for the Anthropic Messages API. */
export class AnthropicMessagesAdapter implements ProviderAdapter {
  /** Construct with resolved auth, base URL and model options. */
  constructor(private readonly opts: AnthropicMessagesOptions) {}

  /** Send a request and yield normalised events to completion. */
  async *sendMessage(request: ModelRequest): AsyncGenerator<HarnessEvent, void, unknown> {
    const baseUrl = this.opts.baseUrl ?? 'https://api.anthropic.com';
    let response: Response;
    try {
      response = await fetch(`${baseUrl}/v1/messages`, {
        method: 'POST',
        headers: buildHeaders(this.opts),
        body: JSON.stringify(buildBody(request, this.opts)),
      });
    } catch (err) {
      // The request never left, or never came back. Reported rather than
      // thrown: a throw here escapes the retry loop entirely, and this is the
      // failure class most likely to succeed on the next attempt.
      yield networkErrorEvent('Anthropic', err);
      return;
    }
    if (!response.ok) {
      yield errorEvent(response.status, await readBody(response), retryAfterMsFrom(response.headers));
      return;
    }
    let payload: unknown;
    try {
      payload = await response.json();
    } catch (err) {
      // The headers arrived and the body did not. undici reports this as
      // `terminated` rather than `fetch failed`, and it is the same transient
      // socket death as a failed connect — a long response over a flapping
      // link is exactly where it happens. Retryable for the same reason: a
      // body we never read cannot have been acted on.
      yield networkErrorEvent('Anthropic', err);
      return;
    }
    yield* emitAnthropicEvents(payload);
  }
}

/** Build an error HarnessEvent for a non-2xx status, carrying the provider's
 * own explanation when it sent one. */
function errorEvent(status: number, body: string, retryAfterMs?: number): HarnessEvent {
  return providerErrorEvent('Anthropic', status, body, RETRYABLE_STATUS.has(status), retryAfterMs);
}

/** Shape of the fields we read from an Anthropic Messages response. */
interface AnthropicResponse {
  content?: AnthropicBlock[];
  usage?: {
    input_tokens?: number;
    output_tokens?: number;
    cache_read_input_tokens?: number;
    cache_creation_input_tokens?: number;
  };
  stop_reason?: unknown;
}

/** Yield text, tool-call, usage and done events from a parsed response. */
function* emitAnthropicEvents(payload: unknown): Generator<HarnessEvent, void, unknown> {
  const body = payload as AnthropicResponse;
  const blocks = body.content ?? [];
  const toolCalls: ToolCall[] = [];
  let text = '';
  for (const block of blocks) {
    const event = blockToEvent(block);
    if (event === undefined) continue;
    if (event.type === 'text') text += event.delta;
    else if (event.type === 'toolCall') toolCalls.push(event.toolCall);
    yield event;
  }
  yield usageEvent(body.usage);
  yield doneEvent(mapStopReason(body.stop_reason), text, toolCalls);
}

/**
 * Build a usage HarnessEvent from Anthropic token counts.
 *
 * The three input counters are summed because `input_tokens` alone excludes
 * the cached prefix — it counts only what was NOT served from cache. On a long
 * agentic run the cached prefix is most of the prompt, so reading
 * `input_tokens` by itself under-reports the context by exactly its largest
 * part, and would tell a compaction check the conversation is small while it
 * is nearly full. Both cache counters are absent today (nothing sets
 * `cache_control`); summing them is what makes this number stay true if
 * caching is ever turned on.
 */
function usageEvent(usage: AnthropicResponse['usage']): HarnessEvent {
  return {
    type: 'usage',
    inputTokens:
      (usage?.input_tokens ?? 0) +
      (usage?.cache_read_input_tokens ?? 0) +
      (usage?.cache_creation_input_tokens ?? 0),
    outputTokens: usage?.output_tokens ?? 0,
  };
}

/** Build the terminal done HarnessEvent with the assembled message. */
function doneEvent(stopReason: StopReason, text: string, toolCalls: ToolCall[]): HarnessEvent {
  const message: ConversationMessage = {
    role: 'assistant',
    content: text,
    ...(toolCalls.length > 0 ? { toolCalls } : {}),
  };
  return { type: 'done', stopReason, message };
}

/** Factory constructing an Anthropic Messages adapter. */
export function createAnthropicMessagesAdapter(opts: AnthropicMessagesOptions): ProviderAdapter {
  return new AnthropicMessagesAdapter(opts);
}
