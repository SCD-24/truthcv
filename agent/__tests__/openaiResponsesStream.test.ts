/**
 * Tests for the SSE stream-parsing behaviour of harness/providers/openaiResponses.ts
 * (via openaiResponsesStream.ts helpers).
 *
 * Stub global fetch (no real network calls). Cover:
 * - Text delta accumulation, output_item.done, output[] fallback, dedupe
 * - Terminal statuses (incomplete/max_output_tokens, unknown status)
 * - Missing call_id handling
 * - Error events and response.failed
 * - Usage events
 * - Stream ending without a completion event
 */

import { describe, expect, it, vi } from "vitest";
import { beforeEach, afterEach } from "vitest";

import { createOpenAiResponsesAdapter } from "../harness/providers/openaiResponses";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a minimal ModelRequest for the adapter. */
function makeRequest(overrides: Partial<{
  systemPrompt: string;
  messages: Array<Record<string, unknown>>;
  tools: Array<{ name: string; description: string; inputSchema: Record<string, unknown> }>;
}> = {}) {
  return {
    systemPrompt: "You are a helpful assistant.",
    messages: [{ role: "user", content: "Hello" }],
    tools: [],
    ...overrides,
  };
}

/** Synthentic JWT with a chatgpt_account_id in the payload. */
function makeJwt(accountId: string): string {
  const payload = btoa(JSON.stringify({
    "https://api.openai.com/auth": { chatgpt_account_id: accountId },
  }));
  return `header.${payload}.sig`;
}

/** Mock fetch to return a successful SSE stream of given event lines. */
function mockStreamResponse(events: string[], status = 200, extraHeaders: Record<string, string> = {}) {
  const body = new ReadableStream({
    start(controller) {
      for (const ev of events) {
        controller.enqueue(new TextEncoder().encode(ev));
      }
      controller.close();
    },
  });
  const headers = new Headers({
    "content-type": "text/event-stream",
    ...extraHeaders,
  });
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    headers,
    body,
  });
}

/** Build a `data: {...}\n` SSE line from an event object. */
function sse(event: unknown): string {
  return `data: ${JSON.stringify(event)}\n`;
}

/** Collect all HarnessEvents from an adapter run. */
async function collect(adapter: ReturnType<typeof createOpenAiResponsesAdapter>, request: ReturnType<typeof makeRequest>) {
  const out: unknown[] = [];
  for await (const ev of adapter.sendMessage(request)) out.push(ev);
  return out;
}

// ---------------------------------------------------------------------------
// SSE parser — reassembly
// ---------------------------------------------------------------------------

describe("SSE reassembly — response.output_text.delta", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

  it("accumulates multiple delta events and stops at response.completed", async () => {
    const events = [
      sse({ type: "response.output_text.delta", delta: "Hello" }),
      sse({ type: "response.output_text.delta", delta: " world" }),
      sse({
        type: "response.completed",
        response: { status: "completed", output: [], usage: { input_tokens: 10, output_tokens: 5 }, model: "gpt-5.4" },
      }),
    ];
    vi.stubGlobal("fetch", mockStreamResponse(events));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const out = await collect(adapter, makeRequest());

    const deltas = out.filter((e: unknown) => (e as { type: string }).type === "text");
    expect(deltas).toHaveLength(2);
    expect((deltas[0] as { delta: string }).delta).toBe("Hello");
    expect((deltas[1] as { delta: string }).delta).toBe(" world");
    const done = out.find((e: unknown) => (e as { type: string }).type === "done");
    expect(done).toBeTruthy();
    expect((done as { stopReason: string }).stopReason).toBe("end");
    expect((done as { message: { content: string } }).message.content).toBe("Hello world");
  });

  it("emits a usage event from response.completed usage/model", async () => {
    const events = [
      sse({
        type: "response.completed",
        response: { status: "completed", output: [], usage: { input_tokens: 42, output_tokens: 7 }, model: "gpt-5.4-mini" },
      }),
    ];
    vi.stubGlobal("fetch", mockStreamResponse(events));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const out = await collect(adapter, makeRequest());
    const usage = out.find((e: unknown) => (e as { type: string }).type === "usage") as
      | { inputTokens: number; outputTokens: number; model?: string }
      | undefined;
    expect(usage).toBeTruthy();
    expect(usage!.inputTokens).toBe(42);
    expect(usage!.outputTokens).toBe(7);
    expect(usage!.model).toBe("gpt-5.4-mini");
  });
});

// ---------------------------------------------------------------------------
// Function calls
// ---------------------------------------------------------------------------

describe("Function calls", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

  it("response.output_item.done with a function_call yields a toolCall and stopReason toolCalls", async () => {
    const events = [
      sse({
        type: "response.output_item.done",
        item: { type: "function_call", call_id: "call_1", name: "search_jobs", arguments: '{"query":"engineer"}' },
      }),
      sse({ type: "response.completed", response: { status: "completed", output: [] } }),
    ];
    vi.stubGlobal("fetch", mockStreamResponse(events));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const out = await collect(adapter, makeRequest());
    const toolCallEvents = out.filter((e: unknown) => (e as { type: string }).type === "toolCall");
    expect(toolCallEvents).toHaveLength(1);
    expect((toolCallEvents[0] as { toolCall: { id: string; name: string } }).toolCall.id).toBe("call_1");
    expect((toolCallEvents[0] as { toolCall: { id: string; name: string } }).toolCall.name).toBe("search_jobs");

    const done = out.find((e: unknown) => (e as { type: string }).type === "done");
    expect((done as { stopReason: string }).stopReason).toBe("toolCalls");
  });

  it("a function_call present only in response.completed output[] is emitted exactly once", async () => {
    const events = [
      sse({
        type: "response.completed",
        response: {
          status: "completed",
          output: [{ type: "function_call", call_id: "call_2", name: "record_application", arguments: "{}" }],
        },
      }),
    ];
    vi.stubGlobal("fetch", mockStreamResponse(events));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const out = await collect(adapter, makeRequest());
    const toolCallEvents = out.filter((e: unknown) => (e as { type: string }).type === "toolCall");
    expect(toolCallEvents).toHaveLength(1);
    expect((toolCallEvents[0] as { toolCall: { id: string } }).toolCall.id).toBe("call_2");
  });

  it("the same call_id in both output_item.done and completed output[] is emitted only once", async () => {
    const item = { type: "function_call", call_id: "call_3", name: "record_application", arguments: "{}" };
    const events = [
      sse({ type: "response.output_item.done", item }),
      sse({ type: "response.completed", response: { status: "completed", output: [item] } }),
    ];
    vi.stubGlobal("fetch", mockStreamResponse(events));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const out = await collect(adapter, makeRequest());
    const toolCallEvents = out.filter((e: unknown) => (e as { type: string }).type === "toolCall");
    expect(toolCallEvents).toHaveLength(1);
  });

  it("an already-seen call_id repeated in output[] with malformed arguments is skipped, not an error", async () => {
    const item = { type: "function_call", call_id: "call_4", name: "record_application", arguments: "{}" };
    const repeat = { ...item, arguments: "{not json" };
    const events = [
      sse({ type: "response.output_item.done", item }),
      sse({ type: "response.completed", response: { status: "completed", output: [repeat] } }),
    ];
    vi.stubGlobal("fetch", mockStreamResponse(events));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const out = (await collect(adapter, makeRequest())) as Array<{ type: string; stopReason?: string }>;
    expect(out.some((e) => e.type === "error")).toBe(false);
    expect(out.find((e) => e.type === "done")?.stopReason).toBe("toolCalls");
  });

  it("a function_call with no call_id yields 'Tool call missing call_id' and no done, via output_item.done", async () => {
    const events = [
      sse({
        type: "response.output_item.done",
        item: { type: "function_call", name: "search_jobs", arguments: "{}" },
      }),
      sse({ type: "response.completed", response: { status: "completed", output: [] } }),
    ];
    vi.stubGlobal("fetch", mockStreamResponse(events));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const out = await collect(adapter, makeRequest());
    const errors = out.filter((e: unknown) => (e as { type: string }).type === "error");
    expect(errors).toHaveLength(1);
    expect((errors[0] as { message: string }).message).toBe("Tool call missing call_id");
    expect((errors[0] as { retryable: boolean }).retryable).toBe(false);
    expect(out.find((e: unknown) => (e as { type: string }).type === "done")).toBeUndefined();
  });

  it("a function_call with an empty call_id in output[] yields 'Tool call missing call_id' and no done", async () => {
    const events = [
      sse({
        type: "response.completed",
        response: {
          status: "completed",
          output: [{ type: "function_call", call_id: "", name: "search_jobs", arguments: "{}" }],
        },
      }),
    ];
    vi.stubGlobal("fetch", mockStreamResponse(events));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const out = await collect(adapter, makeRequest());
    const errors = out.filter((e: unknown) => (e as { type: string }).type === "error");
    expect(errors).toHaveLength(1);
    expect((errors[0] as { message: string }).message).toBe("Tool call missing call_id");
    expect(out.find((e: unknown) => (e as { type: string }).type === "done")).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Terminal statuses
// ---------------------------------------------------------------------------

describe("Terminal statuses", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

  it("response.incomplete with reason max_output_tokens maps to stopReason 'length'", async () => {
    const events = [
      sse({
        type: "response.incomplete",
        response: { status: "incomplete", incomplete_details: { reason: "max_output_tokens" } },
      }),
    ];
    vi.stubGlobal("fetch", mockStreamResponse(events));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const out = await collect(adapter, makeRequest());
    const done = out.find((e: unknown) => (e as { type: string }).type === "done");
    expect(done).toBeTruthy();
    expect((done as { stopReason: string }).stopReason).toBe("length");
  });

  it("an unrecognised status/reason yields an error naming it, and no done event", async () => {
    const events = [
      sse({
        type: "response.incomplete",
        response: { status: "incomplete", incomplete_details: { reason: "content_filter" } },
      }),
    ];
    vi.stubGlobal("fetch", mockStreamResponse(events));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const out = await collect(adapter, makeRequest());
    const done = out.find((e: unknown) => (e as { type: string }).type === "done");
    expect(done).toBeUndefined();
    const errors = out.filter((e: unknown) => (e as { type: string }).type === "error");
    expect(errors).toHaveLength(1);
    expect((errors[0] as { message: string }).message).toContain("content_filter");
  });

  it("a function_call followed by response.incomplete max_output_tokens still maps to 'length'", async () => {
    const events = [
      sse({
        type: "response.output_item.done",
        item: { type: "function_call", call_id: "call_9", name: "search_jobs", arguments: "{}" },
      }),
      sse({
        type: "response.incomplete",
        response: { status: "incomplete", incomplete_details: { reason: "max_output_tokens" } },
      }),
    ];
    vi.stubGlobal("fetch", mockStreamResponse(events));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const out = await collect(adapter, makeRequest());
    const toolCallEvents = out.filter((e: unknown) => (e as { type: string }).type === "toolCall");
    expect(toolCallEvents).toHaveLength(1);
    const done = out.find((e: unknown) => (e as { type: string }).type === "done");
    expect(done).toBeTruthy();
    expect((done as { stopReason: string }).stopReason).toBe("length");
  });

  it("a function_call followed by response.incomplete content_filter yields an error and no done", async () => {
    const events = [
      sse({
        type: "response.output_item.done",
        item: { type: "function_call", call_id: "call_10", name: "search_jobs", arguments: "{}" },
      }),
      sse({
        type: "response.incomplete",
        response: { status: "incomplete", incomplete_details: { reason: "content_filter" } },
      }),
    ];
    vi.stubGlobal("fetch", mockStreamResponse(events));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const out = await collect(adapter, makeRequest());
    const done = out.find((e: unknown) => (e as { type: string }).type === "done");
    expect(done).toBeUndefined();
    const errors = out.filter((e: unknown) => (e as { type: string }).type === "error");
    expect(errors).toHaveLength(1);
    expect((errors[0] as { message: string }).message).toContain("content_filter");
  });
});

// ---------------------------------------------------------------------------
// Error events
// ---------------------------------------------------------------------------

describe("Error events", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

  it("a top-level SSE 'error' event yields an error HarnessEvent with the server code/message", async () => {
    vi.stubGlobal("fetch", mockStreamResponse([
      sse({ type: "error", code: "some_error", message: "Something went wrong." }),
    ]));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const errors = (await collect(adapter, makeRequest())).filter(
      (e: unknown) => (e as { type: string }).type === "error",
    );

    expect(errors).toHaveLength(1);
    expect((errors[0] as { message: string }).message).toBe("some_error: Something went wrong.");
    expect((errors[0] as { retryable: boolean }).retryable).toBe(false);
  });

  it("an SSE 'response.failed' event yields an error HarnessEvent", async () => {
    vi.stubGlobal("fetch", mockStreamResponse([
      sse({ type: "response.failed", response: { error: { code: "internal_error", message: "Something went wrong." } } }),
    ]));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const errors = (await collect(adapter, makeRequest())).filter(
      (e: unknown) => (e as { type: string }).type === "error",
    );

    expect(errors).toHaveLength(1);
    expect((errors[0] as { message: string }).message).toContain("internal_error");
  });
});

// ---------------------------------------------------------------------------
// Stream without completion
// ---------------------------------------------------------------------------

describe("Incomplete stream", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

  it("stream ending without a completion event yields a non-retryable error", async () => {
    vi.stubGlobal("fetch", mockStreamResponse([
      sse({ type: "response.output_text.delta", delta: "partial" }),
    ]));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const errors = (await collect(adapter, makeRequest())).filter(
      (e: unknown) => (e as { type: string }).type === "error",
    );

    expect(errors).toHaveLength(1);
    expect((errors[0] as { message: string }).message).toBe("Stream ended without a completion event");
    expect((errors[0] as { retryable: boolean }).retryable).toBe(false);
  });
});
