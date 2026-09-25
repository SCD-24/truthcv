/**
 * SSE event-mapping helpers for the ChatGPT Codex Responses endpoint.
 *
 * Split out of openaiResponses.ts to keep that file under its line budget.
 * Everything here is about turning parsed Responses SSE events into
 * normalised HarnessEvents; the adapter itself, its request building and
 * its HTTP plumbing stay in openaiResponses.ts.
 */

import type { ConversationMessage, HarnessEvent, StopReason, ToolCall } from "./types.js";

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

/** One item in a Responses `output` array (function call or message). */
export interface ResponseItem {
  type?: string;
  call_id?: string;
  name?: string;
  arguments?: unknown;
  content?: Array<{ type?: string; text?: string }>;
}

/** An error payload as sent by the Responses API. */
export interface ResponseError {
  code?: string;
  message?: string;
  resets_at?: number;
}

/** The `response` object carried by several terminal event types. */
export interface ResponseObject {
  status?: string;
  output?: ResponseItem[];
  usage?: { input_tokens?: number; output_tokens?: number };
  model?: string;
  incomplete_details?: { reason?: string };
  error?: ResponseError;
}

/** Shape of the fields we read from a Responses SSE event. */
export interface ResponseEvent {
  type: string;
  delta?: string;
  item?: ResponseItem;
  response?: ResponseObject;
  code?: string;
  message?: string;
  error?: ResponseError;
}

/** Convert a ReadableStream<Uint8Array> (fetch's default) to an AsyncIterable<string>. */
export async function* streamToText(
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
export async function* parseSSEStream(
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

/** Build the error HarnessEvent for a Responses error payload, mapping the
 * usage-limit family of codes to a clear terminal message. */
export function errorFromObj(err?: ResponseError): HarnessEvent {
  const code = err?.code ?? "unknown";
  const message = err?.message ?? "Unknown error";
  if (code === "usage_limit_reached" || code === "usage_not_included" || code === "rate_limit_exceeded") {
    const resetsMsg = err?.resets_at
      ? ` (resets at ${new Date(err.resets_at * 1000).toISOString()})`
      : "";
    return { type: "error", message: `ChatGPT usage limit reached${resetsMsg}`, retryable: false };
  }
  return { type: "error", message: `${code}: ${message}`, retryable: false };
}

/** Build the error HarnessEvent for a top-level `type: "error"` SSE event,
 * tolerating either flat `code`/`message` fields or a nested `error` object. */
export function errorFromEvent(event: ResponseEvent): HarnessEvent {
  const err: ResponseError | undefined =
    event.error ?? (event.code || event.message ? { code: event.code, message: event.message } : event.response?.error);
  return errorFromObj(err);
}

/** Parse one `function_call` output item into a ToolCall, flagging malformed
 * JSON arguments or a missing call_id rather than throwing. */
export function parseToolCallItem(
  item: ResponseItem,
): { toolCall?: ToolCall; malformed?: true; missingCallId?: true } {
  if (!item.call_id) return { missingCallId: true };
  const parsed = parseArguments(item.arguments);
  if (parsed.error) return { malformed: true };
  return { toolCall: { id: item.call_id, name: item.name ?? "", arguments: parsed.value ?? {} } };
}

/** Collect any `function_call` items from a `response.output[]` array not
 * already seen via `response.output_item.done`, deduping by call_id. */
export function collectFunctionCalls(
  output: ResponseItem[],
  seen: Set<string>,
): { toolCalls: ToolCall[]; malformed: boolean; missingCallId: boolean } {
  const toolCalls: ToolCall[] = [];
  for (const item of output) {
    if (item.type !== "function_call") continue;
    if (item.call_id && seen.has(item.call_id)) continue;
    const parsed = parseToolCallItem(item);
    if (parsed.missingCallId) return { toolCalls, malformed: false, missingCallId: true };
    if (parsed.malformed) return { toolCalls, malformed: true, missingCallId: false };
    const id = item.call_id ?? "";
    if (parsed.toolCall) {
      seen.add(id);
      toolCalls.push(parsed.toolCall);
    }
  }
  return { toolCalls, malformed: false, missingCallId: false };
}

/** Assemble output_text content from `response.output[]` message items, used
 * only when no text deltas arrived during streaming. */
export function textFromOutput(output: ResponseItem[]): string {
  let text = "";
  for (const item of output) {
    if (item.type !== "message") continue;
    for (const part of item.content ?? []) {
      if (part.type === "output_text" && part.text) text += part.text;
    }
  }
  return text;
}

/** Map a terminal status/reason/toolCalls combination to a StopReason, or
 * null when the outcome is not one this adapter can call successful.
 *
 * Terminal status takes precedence over tool calls: a 'completed' response
 * yields 'toolCalls' when any were seen, else 'end'; an 'incomplete'
 * response cut off by the token limit yields 'length' even if tool calls
 * were present (the done message still carries them). Anything else is not
 * recognised as a successful outcome. */
export function mapFinishReason(
  status: string | undefined,
  reason: string | undefined,
  hasToolCalls: boolean,
): StopReason | null {
  if (status === "completed") return hasToolCalls ? "toolCalls" : "end";
  if (status === "incomplete" && reason === "max_output_tokens") return "length";
  return null;
}

/** Build a usage HarnessEvent from Responses token counts, naming the model
 * that served the request when the provider reported one. */
export function usageEvent(usage: NonNullable<ResponseObject["usage"]>, model?: string): HarnessEvent {
  return {
    type: "usage",
    inputTokens: usage.input_tokens ?? 0,
    outputTokens: usage.output_tokens ?? 0,
    ...(model === undefined ? {} : { model }),
  };
}

/** Build the terminal done HarnessEvent with the assembled message. */
export function doneEvent(stopReason: StopReason, text: string, toolCalls: ToolCall[]): HarnessEvent {
  const message: ConversationMessage = {
    role: "assistant",
    content: text,
    ...(toolCalls.length > 0 ? { toolCalls } : {}),
  };
  return { type: "done", stopReason, message };
}

/** Fold any function calls found only in `output[]` into toolCalls, yielding
 * a toolCall event for each. Yields a non-retryable error and returns false
 * when the payload is malformed or a call is missing its call_id. */
function* foldOutputFunctionCalls(
  resp: ResponseObject | undefined,
  toolCalls: ToolCall[],
  seenCallIds: Set<string>,
): Generator<HarnessEvent, boolean, unknown> {
  const fromOutput = collectFunctionCalls(resp?.output ?? [], seenCallIds);
  if (fromOutput.missingCallId) {
    yield { type: "error", message: "Tool call missing call_id", retryable: false };
    return false;
  }
  if (fromOutput.malformed) {
    yield { type: "error", message: "Malformed tool call arguments", retryable: false };
    return false;
  }
  for (const tc of fromOutput.toolCalls) {
    toolCalls.push(tc);
    yield { type: "toolCall", toolCall: tc };
  }
  return true;
}

/** Emit the usage + done events for a resolved status/reason/toolCalls
 * combination, or a non-retryable error for one this adapter does not
 * recognise as a successful outcome. */
function* emitOutcome(
  resp: ResponseObject | undefined,
  finalText: string,
  toolCalls: ToolCall[],
): Generator<HarnessEvent, void, unknown> {
  const status = resp?.status;
  const reason = resp?.incomplete_details?.reason;
  const stopReason = mapFinishReason(status, reason, toolCalls.length > 0);
  if (stopReason === null) {
    yield {
      type: "error",
      retryable: false,
      message: `OpenAI Responses ended with status ${status}${reason ? ` (${reason})` : ""}`,
    };
    return;
  }
  if (resp?.usage) yield usageEvent(resp.usage, resp.model);
  yield doneEvent(stopReason, finalText, toolCalls);
}

/** Handle a `response.completed` or `response.incomplete` terminal event:
 * fold in any function calls only seen in `output[]`, fall back to
 * `output[]` text when no deltas arrived, and emit usage + done, or an
 * error for any status/reason (or malformed call) this adapter does not
 * recognise as success. */
export function* handleTerminalEvent(
  event: ResponseEvent,
  text: string,
  toolCalls: ToolCall[],
  seenCallIds: Set<string>,
): Generator<HarnessEvent, void, unknown> {
  const resp = event.response;
  const ok = yield* foldOutputFunctionCalls(resp, toolCalls, seenCallIds);
  if (!ok) return;
  const finalText = text || textFromOutput(resp?.output ?? []);
  yield* emitOutcome(resp, finalText, toolCalls);
}
