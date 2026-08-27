/**
 * Adapter translating the normalised harness types to and from the
 * OpenAI Chat Completions API (also used by OpenRouter, Codex and Ollama).
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

import { providerErrorEvent, readBody, retryAfterMsFrom } from './errors.js';

/** Options for constructing an OpenAI Chat Completions adapter. */
export interface OpenAiChatCompletionsOptions {
  /** API key sent as a Bearer `authorization` header; omitted when empty. */
  apiKey?: string;
  /** Base URL of the Chat Completions endpoint (no trailing slash). */
  baseUrl: string;
  /** Model identifier to request. */
  model: string;
  /** Optional context window, forwarded as Ollama's `options.num_ctx`. */
  contextWindow?: number;
}

/** HTTP statuses worth retrying. */
const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 504]);

/** Build request headers, omitting auth when no api key is supplied. */
function buildHeaders(apiKey?: string): Record<string, string> {
  const headers: Record<string, string> = { 'content-type': 'application/json' };
  if (apiKey) headers['authorization'] = `Bearer ${apiKey}`;
  return headers;
}

/** Map one tool call to the OpenAI function-calling shape. */
function toOpenAiToolCall(call: ToolCall): unknown {
  return {
    id: call.id,
    type: 'function',
    function: { name: call.name, arguments: JSON.stringify(call.arguments) },
  };
}

/** Expand one normalised message into one or more OpenAI messages. */
function toOpenAiMessages(message: ConversationMessage): unknown[] {
  if (message.toolResults && message.toolResults.length > 0)
    return message.toolResults.map((result) => ({
      role: 'tool',
      tool_call_id: result.toolCallId,
      content: result.content,
    }));
  const mapped: Record<string, unknown> = { role: message.role, content: message.content };
  if (message.toolCalls && message.toolCalls.length > 0)
    mapped['tool_calls'] = message.toolCalls.map(toOpenAiToolCall);
  return [mapped];
}

/** Map normalised tool definitions to OpenAI's function-tool shape. */
function toOpenAiTools(tools: ToolDefinition[]): unknown[] {
  return tools.map((tool) => ({
    type: 'function',
    function: { name: tool.name, description: tool.description, parameters: tool.inputSchema },
  }));
}

/** Assemble the full Chat Completions request body from a ModelRequest. */
function buildBody(request: ModelRequest, opts: OpenAiChatCompletionsOptions): unknown {
  const messages = [
    { role: 'system', content: request.systemPrompt },
    ...request.messages.flatMap(toOpenAiMessages),
  ];
  const body: Record<string, unknown> = { model: opts.model, messages, tools: toOpenAiTools(request.tools) };
  if (request.maxTokens !== undefined) body['max_tokens'] = request.maxTokens;
  if (opts.contextWindow !== undefined) body['options'] = { num_ctx: opts.contextWindow };
  return body;
}

/** Translate an OpenAI finish_reason to a normalised StopReason. */
function mapFinishReason(reason: unknown): StopReason {
  if (reason === 'stop') return 'end';
  if (reason === 'tool_calls') return 'toolCalls';
  if (reason === 'length') return 'length';
  return 'error';
}

/** Parse a tool call's JSON-string arguments, flagging malformed input. */
function parseArguments(raw: unknown): { value?: Record<string, unknown>; error?: true } {
  try {
    return { value: JSON.parse((raw as string) ?? '{}') as Record<string, unknown> };
  } catch {
    return { error: true };
  }
}

/** Shape of the fields we read from an OpenAI tool_calls entry. */
interface OpenAiToolCall {
  id?: string;
  function?: { name?: string; arguments?: unknown };
}

/** Shape of the fields we read from an OpenAI Chat Completions response. */
interface OpenAiResponse {
  choices?: Array<{
    message?: { content?: string | null; tool_calls?: OpenAiToolCall[] };
    finish_reason?: unknown;
  }>;
  usage?: { prompt_tokens?: number; completion_tokens?: number };
}

/** Adapter for the OpenAI Chat Completions API. */
export class OpenAiChatCompletionsAdapter implements ProviderAdapter {
  /** Construct with resolved auth, base URL and model options. */
  constructor(private readonly opts: OpenAiChatCompletionsOptions) {}

  /** Send a request and yield normalised events to completion. */
  async *sendMessage(request: ModelRequest): AsyncGenerator<HarnessEvent, void, unknown> {
    const response = await fetch(`${this.opts.baseUrl}/chat/completions`, {
      method: 'POST',
      headers: buildHeaders(this.opts.apiKey),
      body: JSON.stringify(buildBody(request, this.opts)),
    });
    if (!response.ok) {
      yield errorEvent(response.status, await readBody(response), retryAfterMsFrom(response.headers));
      return;
    }
    yield* emitOpenAiEvents(await response.json());
  }
}

/** Build an error HarnessEvent for a non-2xx status, carrying the provider's
 * own explanation when it sent one. */
function errorEvent(status: number, body: string, retryAfterMs?: number): HarnessEvent {
  return providerErrorEvent('OpenAI', status, body, RETRYABLE_STATUS.has(status), retryAfterMs);
}

/** Yield text, tool-call, usage and done events from a parsed response. */
function* emitOpenAiEvents(payload: unknown): Generator<HarnessEvent, void, unknown> {
  const body = payload as OpenAiResponse;
  const choice = body.choices?.[0];
  const text = choice?.message?.content ?? '';
  if (text) yield { type: 'text', delta: text };
  const toolCalls: ToolCall[] = [];
  for (const raw of choice?.message?.tool_calls ?? []) {
    const parsed = parseArguments(raw.function?.arguments);
    if (parsed.error) {
      yield { type: 'error', message: 'Malformed tool call arguments', retryable: false };
      return;
    }
    const toolCall: ToolCall = { id: raw.id ?? '', name: raw.function?.name ?? '', arguments: parsed.value ?? {} };
    toolCalls.push(toolCall);
    yield { type: 'toolCall', toolCall };
  }
  yield usageEvent(body.usage);
  yield doneEvent(mapFinishReason(choice?.finish_reason), text, toolCalls);
}

/** Build a usage HarnessEvent from OpenAI token counts. */
function usageEvent(usage: OpenAiResponse['usage']): HarnessEvent {
  return {
    type: 'usage',
    inputTokens: usage?.prompt_tokens ?? 0,
    outputTokens: usage?.completion_tokens ?? 0,
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

/** Factory constructing an OpenAI Chat Completions adapter. */
export function createOpenAiChatCompletionsAdapter(
  opts: OpenAiChatCompletionsOptions,
): ProviderAdapter {
  return new OpenAiChatCompletionsAdapter(opts);
}
