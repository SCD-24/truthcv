/**
 * Adapter for the ChatGPT Codex Responses endpoint via SSE streaming.
 *
 * The Responses API is streaming-only (no non-streaming mode). Tokens are sent
 * as SSE event lines; this adapter assembles them and yields normalised harness
 * events. The chatgpt_account_id is derived from the OAuth token's JWT on
 * each call rather than stored. SSE event-mapping helpers live in
 * openaiResponsesStream.ts.
 */

import type {
  ConversationMessage,
  HarnessEvent,
  ModelRequest,
  ProviderAdapter,
  ToolCall,
  ToolDefinition,
  ToolResult,
} from "./types.js";

import { networkErrorEvent, providerErrorEvent, readBody } from "./errors.js";
import {
  errorFromEvent,
  errorFromObj,
  handleTerminalEvent,
  parseSSEStream,
  parseToolCallItem,
  streamToText,
  type ResponseEvent,
  type ResponseItem,
} from "./openaiResponsesStream.js";

/** Options for constructing an OpenAI Responses adapter. */
export interface OpenAiResponsesOptions {
  /** OAuth bearer token (access token from device-code flow). */
  token: string;
  /** Base URL for the Responses endpoint; defaults to the ChatGPT production URL. */
  baseUrl?: string;
  /** Model identifier to request. */
  model: string;
}

/** Statuses worth retrying. */
const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 504]);

/** Map one queued tool call to a Responses `function_call` input item. */
function functionCallItem(tc: ToolCall): unknown {
  return { type: "function_call", call_id: tc.id, name: tc.name, arguments: JSON.stringify(tc.arguments) };
}

/** Map one tool result to a Responses `function_call_output` input item. */
function functionCallOutputItem(tr: ToolResult): unknown {
  return { type: "function_call_output", call_id: tr.toolCallId, output: tr.content };
}

/** Translate normalised conversation messages into real Responses input items. */
function toResponsesInput(messages: ConversationMessage[]): unknown[] {
  const items: unknown[] = [];
  for (const msg of messages) {
    if (msg.role === "assistant") {
      if (msg.content) items.push({ role: "assistant", content: msg.content });
      for (const tc of msg.toolCalls ?? []) items.push(functionCallItem(tc));
    } else if (msg.content) {
      items.push({ role: msg.role, content: msg.content });
    }
    for (const tr of msg.toolResults ?? []) items.push(functionCallOutputItem(tr));
  }
  return items;
}

/** Build request headers for the Responses endpoint. */
function buildHeaders(token: string, accountId: string): Record<string, string> {
  return {
    authorization: `Bearer ${token}`,
    "chatgpt-account-id": accountId,
    originator: "truthcv",
    "user-agent": "truthcv-agent",
    "openai-organization": "truthcv",
    "openai-beta": "responses=experimental",
    accept: "text/event-stream",
    "content-type": "application/json",
  };
}

/** Build the request body from a ModelRequest and options. */
function buildBody(
  request: ModelRequest,
  opts: OpenAiResponsesOptions,
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    model: opts.model,
    store: false,
    stream: true,
    instructions: request.systemPrompt,
    input: toResponsesInput(request.messages),
    include: ["reasoning.encrypted_content"],
    parallel_tool_calls: true,
    tool_choice: "auto",
  };
  if (request.tools.length > 0) {
    body.tools = request.tools.map((tool) => ({
      type: "function",
      name: tool.name,
      description: tool.description,
      parameters: tool.inputSchema,
    }));
  }
  // NOTE: no max_output_tokens is sent — the backend rejects it.
  return body;
}

/** Extract the chatgpt_account_id from a JWT token via base64url decode. */
export function accountIdFromToken(token: string): string {
  try {
    const parts = token.split(".");
    if (parts.length < 2) return "";
    let payloadB64 = parts[1];
    // Add padding for base64url decode (which is standard base64)
    const pad = 4 - (payloadB64.length % 4);
    if (pad < 4) payloadB64 += "=".repeat(pad);
    const payload = JSON.parse(atob(payloadB64)) as Record<string, unknown>;
    const auth = (payload["https://api.openai.com/auth"] as Record<string, unknown>) || {};
    const accountId = auth["chatgpt_account_id"];
    return typeof accountId === "string" ? accountId : "";
  } catch {
    return "";
  }
}

/** Adapter for the ChatGPT Codex Responses endpoint. */
export class OpenAiResponsesAdapter implements ProviderAdapter {
  constructor(private readonly opts: OpenAiResponsesOptions) {}

  async *sendMessage(request: ModelRequest): AsyncGenerator<HarnessEvent, void, unknown> {
    const accountId = accountIdFromToken(this.opts.token);
    const baseUrl = this.opts.baseUrl || "https://chatgpt.com/backend-api/codex";
    const url = `${baseUrl}/responses`;
    const headers = buildHeaders(this.opts.token, accountId);
    const body = buildBody(request, this.opts);

    let response: Response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });
    } catch (err) {
      yield networkErrorEvent("OpenAI Responses", err);
      return;
    }

    if (!response.ok) {
      const bodyText = await readBody(response);
      yield* this._handleError(response.status, bodyText);
      return;
    }

    if (!response.body) {
      yield networkErrorEvent("OpenAI Responses", new Error("Response body is null"));
      return;
    }

    yield* this._handleStream(response.body);
  }

  private async *_handleError(status: number, bodyText: string): AsyncGenerator<HarnessEvent, void, unknown> {
    // Map usage-limit errors to a clear terminal message
    if (
      status === 429 ||
      bodyText.includes("usage_limit_reached") ||
      bodyText.includes("usage_not_included") ||
      bodyText.includes("rate_limit_exceeded")
    ) {
      let resetsAt: number | undefined;
      try {
        const errBody = JSON.parse(bodyText);
        const errorObj =
          (errBody.error && typeof errBody.error === "object" ? errBody.error : null) ||
          (errBody.detail && typeof errBody.detail === "object" ? errBody.detail : null);
        if (errorObj && typeof errorObj === "object") {
          const raw = (errorObj as Record<string, unknown>)["resets_at"];
          if (typeof raw === "number") resetsAt = raw;
        }
      } catch {
        // ignore parse failure
      }
      const resetsMsg = resetsAt
        ? ` (resets at ${new Date(resetsAt * 1000).toISOString()})`
        : "";
      yield {
        type: "error",
        message: `ChatGPT usage limit reached${resetsMsg}`,
        retryable: false,
      };
      return;
    }
    yield providerErrorEvent(
      "OpenAI Responses",
      status,
      bodyText,
      RETRYABLE_STATUS.has(status),
    );
  }

  /** Handle one `response.output_item.done` event: pick up a completed
   * function call not already recorded, deduping by call_id. Returns false
   * when the stream should end (malformed arguments or missing call_id). */
  private *_handleOutputItemDone(
    item: ResponseItem | undefined,
    toolCalls: ToolCall[],
    seenCallIds: Set<string>,
  ): Generator<HarnessEvent, boolean, unknown> {
    if (item?.type !== "function_call") return true;
    const parsed = parseToolCallItem(item);
    if (parsed.missingCallId) {
      yield { type: "error", message: "Tool call missing call_id", retryable: false };
      return false;
    }
    const id = item.call_id ?? "";
    if (seenCallIds.has(id)) return true;
    if (parsed.malformed) {
      yield { type: "error", message: "Malformed tool call arguments", retryable: false };
      return false;
    }
    if (parsed.toolCall) {
      seenCallIds.add(id);
      toolCalls.push(parsed.toolCall);
      yield { type: "toolCall", toolCall: parsed.toolCall };
    }
    return true;
  }

  /** Process one parsed SSE event: accumulate text deltas, dispatch
   * function-call and terminal events, and mutate the running text via
   * `state`. Returns false when the stream should end. */
  private *_handleEvent(
    event: ResponseEvent, state: { text: string }, toolCalls: ToolCall[], seenCallIds: Set<string>,
  ): Generator<HarnessEvent, boolean, unknown> {
    switch (event.type) {
      case "response.output_text.delta":
        return yield* this._handleTextDelta(event.delta, state);
      case "response.output_item.done":
        return yield* this._handleOutputItemDone(event.item, toolCalls, seenCallIds);
      case "error":
        yield errorFromEvent(event);
        return false;
      case "response.failed":
        yield errorFromObj(event.response?.error);
        return false;
      case "response.completed":
      case "response.incomplete":
        yield* handleTerminalEvent(event, state.text, toolCalls, seenCallIds);
        return false;
      default:
        return true;
    }
  }

  /** Append a text delta to the running text and forward it as a text event. */
  private *_handleTextDelta(
    delta: string | undefined,
    state: { text: string },
  ): Generator<HarnessEvent, boolean, unknown> {
    if (delta) {
      state.text += delta;
      yield { type: "text", delta };
    }
    return true;
  }

  /** Read the SSE body event by event, yielding normalised harness events;
   * reports an error if the stream closes without a terminal event. */
  private async *_handleStream(
    body: ReadableStream<Uint8Array>,
  ): AsyncGenerator<HarnessEvent, void, unknown> {
    const state = { text: "" };
    const toolCalls: ToolCall[] = [];
    const seenCallIds = new Set<string>();

    for await (const event of parseSSEStream(streamToText(body))) {
      const cont = yield* this._handleEvent(event, state, toolCalls, seenCallIds);
      if (!cont) return;
    }

    // Stream ended without a completion event
    yield { type: "error", message: "Stream ended without a completion event", retryable: false };
  }
}

/** Factory constructing an OpenAI Responses adapter. */
export function createOpenAiResponsesAdapter(opts: OpenAiResponsesOptions): ProviderAdapter {
  return new OpenAiResponsesAdapter(opts);
}
