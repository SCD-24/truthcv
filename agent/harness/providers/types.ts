/**
 * Vendor-neutral model-call types shared by every provider adapter.
 *
 * Nothing in this module leaks an Anthropic- or OpenAI-specific wire field;
 * adapters translate to and from these shapes at their edges.
 */

/** The author of a conversation message. */
export type Role = 'system' | 'user' | 'assistant' | 'tool';

/** A tool the model may call, described with a JSON-schema input shape. */
export interface ToolDefinition {
  /** Unique tool name the model references when calling it. */
  name: string;
  /** Human-readable description of what the tool does. */
  description: string;
  /** JSON-schema-shaped description of the tool's arguments. */
  inputSchema: Record<string, unknown>;
}

/** A single request from the model to invoke a tool. */
export interface ToolCall {
  /** Provider-assigned identifier correlating the call to its result. */
  id: string;
  /** Name of the tool being invoked. */
  name: string;
  /** Parsed argument object passed to the tool. */
  arguments: Record<string, unknown>;
}

/** The outcome of executing a tool call, fed back to the model. */
export interface ToolResult {
  /** Id of the ToolCall this result answers. */
  toolCallId: string;
  /** Serialized tool output returned to the model. */
  content: string;
  /** True when the tool execution failed. */
  isError?: boolean;
}

/** One turn of the conversation in normalised form. */
export interface ConversationMessage {
  /** Author of the message. */
  role: Role;
  /** Plain-text content of the message. */
  content: string;
  /** Tool calls the assistant requested in this turn, if any. */
  toolCalls?: ToolCall[];
  /** Tool results supplied for prior calls, if any. */
  toolResults?: ToolResult[];
}

/** Why the model stopped generating. */
export type StopReason = 'toolCalls' | 'end' | 'length' | 'error' | 'aborted';

/** A single streamed or assembled event emitted by an adapter. */
export type HarnessEvent =
  /** Incremental assistant text. */
  | { type: 'text'; delta: string }
  /** Incremental model reasoning text. */
  | { type: 'reasoning'; delta: string }
  /** A tool the model wants to invoke. */
  | { type: 'toolCall'; toolCall: ToolCall }
  /** Token accounting for the request. */
  | {
      type: 'usage';
      inputTokens: number;
      outputTokens: number;
      /** Anthropic-only: tokens served from the prompt cache. Present only when
       * the provider reports it; absent on OpenAI-wire responses. */
      cacheReadTokens?: number;
      /** Anthropic-only: tokens written into the prompt cache. Present only when
       * the provider reports it; absent on OpenAI-wire responses. */
      cacheWriteTokens?: number;
      /** The model that actually served this request, as the provider reported
       * it. Present only when it says: a router such as OpenRouter's
       * `openrouter/free` picks a different backing model per request, so the
       * configured id does not identify what produced a given turn. */
      model?: string;
    }
  /** Terminal event carrying the stop reason and assembled message. */
  | { type: 'done'; stopReason: StopReason; message: ConversationMessage }
  /** A recoverable or fatal error surfaced instead of throwing. */
  | {
      type: 'error';
      message: string;
      retryable: boolean;
      /** How long the provider asked us to wait, in ms, from its `Retry-After`
       * header. Absent when it sent none. The loop prefers this over its own
       * computed backoff: the provider knows when its limit resets and we do
       * not. */
      retryAfterMs?: number;
    };

/** A normalised request sent to a provider adapter. */
export interface ModelRequest {
  /** System prompt establishing the model's behaviour. */
  systemPrompt: string;
  /** Conversation history in chronological order. */
  messages: ConversationMessage[];
  /** Tools the model is allowed to call. */
  tools: ToolDefinition[];
  /** Optional cap on generated tokens. */
  maxTokens?: number;
}

/** A provider-agnostic interface for calling a model. */
export interface ProviderAdapter {
  /** Send a request and stream normalised events to completion. */
  sendMessage(request: ModelRequest): AsyncGenerator<HarnessEvent, void, unknown>;
}
