/**
 * Adapter for the ChatGPT Codex Responses endpoint via SSE streaming.
 *
 * The Responses API is streaming-only (no non-streaming mode). Tokens are sent
 * as SSE event lines; this adapter assembles them and yields normalised harness
 * events. The chatgpt_account_id is derived from the OAuth token's JWT on
 * each call rather than stored.
 */

import type {
  ConversationMessage,
  HarnessEvent,
  ModelRequest,
  ProviderAdapter,
  StopReason,
  ToolCall,
  ToolDefinition,
} from "./types.js";

import { networkErrorEvent, providerErrorEvent, readBody } from "./errors.js";

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

/** Map a model stop reason to a normalised StopReason. */
function mapFinishReason(reason: unknown): StopReason {
  if (reason === "stop" || reason === "end_turn") return "end";
  if (reason === "tool_calls") return "toolCalls";
  if (reason === "max_output_tokens") return "length";
  return "error";
}

/** Parse a tool call's JSON-string arguments, flagging malformed input. */
function parseArguments(
  raw: unknown,
): { value?: Record<string, unknown>; error?: true } {
  try {
    return { value: JSON.parse((raw as string) ?? "{}") as Record<string, unknown> };
  } catch {
    return { error: true };
  }
}

/** Shape of the fields we read from a Responses SSE event. */
interface ResponseEvent {
  type: string;
  response?: {
    output_text?: { delta?: string };
    completed_reason?: unknown;
    outputs?: Array<{
      type?: string;
      id?: string;
      name?: string;
      arguments?: unknown;
    }>;
    error?: { code?: string; message?: string };
  };
}

/** Convert a ReadableStream<Uint8Array> (fetch's default) to an AsyncIterable<string>. */
async function* streamToText(
  body: ReadableStream<Uint8Array>,
): AsyncIterable<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  try {
    let result: ReadableStreamReadResult<Uint8Array>;
    while ((result = await reader.read()), !result.done) {
      yield decoder.decode(result.value, { stream: true });
    }
    // Flush any remaining bytes in the decoder
    yield decoder.decode(undefined, { stream: false });
  } finally {
    reader.releaseLock();
  }
}

/** Parse SSE lines from an async text iterable into structured events.
 *
 * Yields parsed JSON objects found after "data: " prefixes.
 * ["DONE"] and empty payloads are skipped.
 */
async function* parseSSEStream(
  lines: AsyncIterable<string>,
): AsyncGenerator<ResponseEvent, void, unknown> {
  let buffer = "";
  for await (const chunk of lines) {
    buffer += chunk;
    const parts = buffer.split("\n");
    buffer = parts.pop() ?? "";

    for (const line of parts) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data: ")) continue;
      const data = trimmed.slice("data: ".length).trim();
      if (data === "[DONE]" || data === "") continue;
      try {
        yield JSON.parse(data) as ResponseEvent;
      } catch {
        // Skip unparseable lines
      }
    }
  }
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
    input: request.messages,
    include: ["reasoning.encrypted_content"],
    parallel_tool_calls: true,
    tool_choice: "auto",
  };
  if (request.tools.length > 0) {
    body.tools = request.tools.map((tool) => ({
      type: "function",
      function: {
        name: tool.name,
        description: tool.description,
        parameters: tool.inputSchema,
      },
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

    yield* this._handleStream(response.body, accountId);
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

  private async *_handleStream(
    body: ReadableStream<Uint8Array>,
    _accountId: string,
  ): AsyncGenerator<HarnessEvent, void, unknown> {
    let text = "";
    const toolCalls: ToolCall[] = [];
    let stopReason: StopReason = "error";
    let seenCompleted = false;

    for await (const event of parseSSEStream(streamToText(body))) {
      const resp = event.response;
      if (!resp) continue;

      // error event
      if (event.type === "error" || resp.error) {
        const code =
          (resp.error && typeof resp.error === "object"
            ? (resp.error as Record<string, unknown>).code
            : undefined) || "unknown";
        const message =
          (resp.error && typeof resp.error === "object"
            ? (resp.error as Record<string, unknown>).message
            : undefined) || "Unknown error";
        if (
          code === "usage_limit_reached" ||
          code === "usage_not_included" ||
          code === "rate_limit_exceeded"
        ) {
          let resetsAt: number | undefined;
          const rawReset = (resp.error && typeof resp.error === "object"
            ? (resp.error as Record<string, unknown>).resets_at
            : undefined);
          if (typeof rawReset === "number") resetsAt = rawReset;
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
        yield { type: "error", message: `${code}: ${message}`, retryable: false };
        return;
      }

      // Text delta
      if (resp.output_text?.delta) {
        text += resp.output_text.delta;
        yield { type: "text", delta: resp.output_text.delta };
      }

      // Tool calls in response.outputs
      if (resp.outputs) {
        for (const output of resp.outputs) {
          if (output.type === "function_call" || output.type === "function") {
            const parsed = parseArguments(output.arguments);
            if (parsed.error) {
              yield { type: "error", message: "Malformed tool call arguments", retryable: false };
              return;
            }
            const toolCall: ToolCall = {
              id: output.id ?? "",
              name: typeof (output as Record<string, unknown>).name === "string"
                ? String((output as Record<string, unknown>).name)
                : "",
              arguments: parsed.value ?? {},
            };
            toolCalls.push(toolCall);
            yield { type: "toolCall", toolCall };
          }
        }
      }

      // response.completed
      if (event.type === "response.completed") {
        seenCompleted = true;
        stopReason = mapFinishReason(resp.completed_reason);
        break;
      }

      // response.failed
      if (event.type === "response.failed") {
        const errObj = (resp.error || {}) as Record<string, unknown>;
        const code = (typeof errObj.code === "string" ? errObj.code : undefined) || "unknown";
        const message = (typeof errObj.message === "string" ? errObj.message : undefined) || "Unknown failure";
        yield { type: "error", message: `${code}: ${message}`, retryable: false };
        return;
      }
    }

    // Stream ended without a completion event
    if (!seenCompleted) {
      yield { type: "error", message: "Stream ended without a completion event", retryable: false };
      return;
    }

    const message: ConversationMessage = {
      role: "assistant",
      content: text,
      ...(toolCalls.length > 0 ? { toolCalls } : {}),
    };
    yield { type: "done", stopReason, message };
  }
}

/** Factory constructing an OpenAI Responses adapter. */
export function createOpenAiResponsesAdapter(opts: OpenAiResponsesOptions): ProviderAdapter {
  return new OpenAiResponsesAdapter(opts);
}
