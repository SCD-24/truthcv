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

/** Build the request headers, choosing api-key or OAuth auth. */
function buildHeaders(opts: AnthropicMessagesOptions): Record<string, string> {
  const headers: Record<string, string> = {
    'anthropic-version': '2023-06-01',
    'content-type': 'application/json',
  };
  if (opts.oauthToken) headers['authorization'] = `Bearer ${opts.oauthToken}`;
  else if (opts.apiKey) headers['x-api-key'] = opts.apiKey;
  return headers;
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
function buildBody(request: ModelRequest, model: string): unknown {
  return {
    model,
    max_tokens: request.maxTokens ?? 4096,
    system: request.systemPrompt,
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
    const response = await fetch(`${baseUrl}/v1/messages`, {
      method: 'POST',
      headers: buildHeaders(this.opts),
      body: JSON.stringify(buildBody(request, this.opts.model)),
    });
    if (!response.ok) {
      yield errorEvent(response.status);
      return;
    }
    yield* emitAnthropicEvents(await response.json());
  }
}

/** Build an error HarnessEvent for a non-2xx status. */
function errorEvent(status: number): HarnessEvent {
  return {
    type: 'error',
    message: `Anthropic request failed with status ${status}`,
    retryable: RETRYABLE_STATUS.has(status),
  };
}

/** Shape of the fields we read from an Anthropic Messages response. */
interface AnthropicResponse {
  content?: AnthropicBlock[];
  usage?: { input_tokens?: number; output_tokens?: number };
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

/** Build a usage HarnessEvent from Anthropic token counts. */
function usageEvent(usage: AnthropicResponse['usage']): HarnessEvent {
  return {
    type: 'usage',
    inputTokens: usage?.input_tokens ?? 0,
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
