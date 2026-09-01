/**
 * Tests for harness/providers/openaiResponses.ts
 *
 * Stub global fetch (no real network calls). Cover:
 * - Request URL, headers, body correctness
 * - SSE parser: multiple delta events assembled + stop at response.completed
 * - Error event and response.failed event surface as error HarnessEvents
 * - HTTP 429 + usage_limit_reached code => terminal usage-limit error with resets_at
 * - Stream ending without response.completed => throws
 * - createProviderAdapter routes wire 'openai-responses', 'anthropic-messages',
 *   'openai-chat-completions', and throws on unknown wire
 */

import { describe, expect, it, vi } from "vitest";
import { beforeEach, afterEach } from "vitest";

import {
  createOpenAiResponsesAdapter,
  accountIdFromToken,
  type OpenAiResponsesOptions,
} from "../harness/providers/openaiResponses";
import { createProviderAdapter } from "../harness/providers/registry";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a minimal ModelRequest for the adapter. */
function makeRequest(overrides: Partial<{
  systemPrompt: string;
  messages: Array<{ role: string; content: string }>;
  tools: Array<{ name: string; description: string; inputSchema: Record<string, unknown> }>;
  maxTokens: number;
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

// ---------------------------------------------------------------------------
// accountIdFromToken
// ---------------------------------------------------------------------------

describe("accountIdFromToken", () => {
  it("extracts chatgpt_account_id from a valid JWT", () => {
    expect(accountIdFromToken(makeJwt("acct-abc-1"))).toBe("acct-abc-1");
  });

  it("returns empty string for a malformed token", () => {
    expect(accountIdFromToken("not.a.jwt")).toBe("");
    expect(accountIdFromToken("onlyonepart")).toBe("");
    expect(accountIdFromToken("")).toBe("");
  });
});

// ---------------------------------------------------------------------------
// createOpenAiResponsesAdapter — happy path
// ---------------------------------------------------------------------------

describe("createOpenAiResponsesAdapter — request correctness", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("sends the request to the correct URL with required headers", async () => {
    const fetchMock = mockStreamResponse(["data: [DONE]\n"]);
    vi.stubGlobal("fetch", fetchMock);

    const adapter = createOpenAiResponsesAdapter({
      token: makeJwt("acct-test"),
      model: "gpt-5.4",
    });

    await adapter.sendMessage(makeRequest()).next();

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("https://chatgpt.com/backend-api/codex/responses");
    // headers is a plain object from our buildHeaders() call
    const hdrs = init.headers as Record<string, string>;
    expect(hdrs["authorization"]).toMatch(/^Bearer /);
    expect(hdrs["chatgpt-account-id"]).toBe("acct-test");
    expect(hdrs["openai-beta"]).toBe("responses=experimental");
    expect(hdrs["accept"]).toBe("text/event-stream");
    expect(hdrs["content-type"]).toBe("application/json");
  });

  it("sets store:false and stream:true and omits max_output_tokens", async () => {
    const fetchMock = mockStreamResponse(["data: [DONE]\n"]);
    vi.stubGlobal("fetch", fetchMock);

    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });
    await adapter.sendMessage(makeRequest()).next();

    const [, init] = fetchMock.mock.calls[0]!;
    const body = JSON.parse((init.body as string));
    expect(body.store).toBe(false);
    expect(body.stream).toBe(true);
    expect(body).not.toHaveProperty("max_output_tokens");
  });
});

// ---------------------------------------------------------------------------
// SSE parser — reassembly
// ---------------------------------------------------------------------------

describe("SSE reassembly — response.output_text.delta", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

  it("accumulates multiple delta events and stops at response.completed", async () => {
    const events = [
      'data: {"type":"response.output_text.delta","response":{"output_text":{"delta":"Hello"}}}\n',
      'data: {"type":"response.output_text.delta","response":{"output_text":{"delta":" world"}}}\n',
      'data: {"type":"response.completed","response":{"completed_reason":"stop"}}\n',
    ];
    vi.stubGlobal("fetch", mockStreamResponse(events));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const events_out: unknown[] = [];
    for await (const ev of adapter.sendMessage(makeRequest())) {
      events_out.push(ev);
    }

    const deltas = events_out.filter((e: unknown) => (e as { type: string }).type === "text");
    expect(deltas).toHaveLength(2);
    expect((deltas[0] as { delta: string }).delta).toBe("Hello");
    expect((deltas[1] as { delta: string }).delta).toBe(" world");
    const done = events_out.find((e: unknown) => (e as { type: string }).type === "done");
    expect(done).toBeTruthy();
    expect((done as { stopReason: string }).stopReason).toBe("end");
  });
});

// ---------------------------------------------------------------------------
// Error events
// ---------------------------------------------------------------------------

describe("Error events", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

  it("an SSE 'error' event yields an error HarnessEvent with the server code/message", async () => {
    vi.stubGlobal("fetch", mockStreamResponse([
      'data: {"type":"error","response":{"error":{"code":"some_error","message":"Something went wrong."}}}\n',
    ]));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const errors: unknown[] = [];
    for await (const ev of adapter.sendMessage(makeRequest())) {
      if ((ev as { type: string }).type === "error") errors.push(ev);
    }

    expect(errors).toHaveLength(1);
    expect((errors[0] as { message: string }).message).toBe("some_error: Something went wrong.");
    expect((errors[0] as { retryable: boolean }).retryable).toBe(false);
  });

  it("an SSE 'response.failed' event yields an error HarnessEvent", async () => {
    vi.stubGlobal("fetch", mockStreamResponse([
      'data: {"type":"response.failed","response":{"error":{"code":"internal_error","message":"Something went wrong."}}}\n',
    ]));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const errors: unknown[] = [];
    for await (const ev of adapter.sendMessage(makeRequest())) {
      if ((ev as { type: string }).type === "error") errors.push(ev);
    }

    expect(errors).toHaveLength(1);
    expect((errors[0] as { message: string }).message).toContain("internal_error");
  });

  it("HTTP 429 with usage_limit_reached code yields terminal usage-limit error with resets_at", async () => {
    // Mock a JSON body response (not SSE) for the non-streaming error path
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 429,
      headers: new Headers({ "content-type": "application/json" }),
      async text() {
        return JSON.stringify({
          error: { code: "usage_limit_reached", message: "Limit reached.", resets_at: 1234567890 },
        });
      },
    }));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const errors: unknown[] = [];
    for await (const ev of adapter.sendMessage(makeRequest())) {
      if ((ev as { type: string }).type === "error") errors.push(ev);
    }

    expect(errors).toHaveLength(1);
    expect((errors[0] as { message: string }).message).toContain("usage limit reached");
    expect((errors[0] as { message: string }).message).toContain("resets at");
    expect((errors[0] as { retryable: boolean }).retryable).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Stream without completion
// ---------------------------------------------------------------------------

describe("Incomplete stream", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

  it("stream ending without response.completed throws a non-retryable error", async () => {
    vi.stubGlobal("fetch", mockStreamResponse([
      'data: {"type":"response.output_text.delta","response":{"output_text":{"delta":"partial"}}}\n',
    ]));
    const adapter = createOpenAiResponsesAdapter({ token: makeJwt("a"), model: "gpt-5.4" });

    const errors: unknown[] = [];
    for await (const ev of adapter.sendMessage(makeRequest())) {
      if ((ev as { type: string }).type === "error") errors.push(ev);
    }

    expect(errors).toHaveLength(1);
    expect((errors[0] as { message: string }).message).toContain("completion");
    expect((errors[0] as { retryable: boolean }).retryable).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// createProviderAdapter routing
// ---------------------------------------------------------------------------

describe("createProviderAdapter — wire routing", () => {
  const minimalOptions = {
    provider: "codex" as const,
    model: "gpt-5.4",
    token: makeJwt("a"),
    baseUrl: "",
    authType: "oauth" as const,
  };

  it("returns the Responses adapter for wire 'openai-responses'", () => {
    const adapter = createProviderAdapter({ ...minimalOptions, wire: "openai-responses" });
    // It should be an instance of the Responses adapter (check via duck-typing)
    expect(typeof adapter.sendMessage).toBe("function");
  });

  it("returns the Anthropic adapter for wire 'anthropic-messages'", () => {
    const adapter = createProviderAdapter({
      ...minimalOptions,
      provider: "claude",
      wire: "anthropic-messages",
      token: "sk-ant-test",
    });
    expect(typeof adapter.sendMessage).toBe("function");
  });

  it("returns the Chat Completions adapter for wire 'openai-chat-completions'", () => {
    const adapter = createProviderAdapter({
      ...minimalOptions,
      wire: "openai-chat-completions",
      token: "sk-test",
    });
    expect(typeof adapter.sendMessage).toBe("function");
  });

  it("throws on an unknown wire string", () => {
    expect(() =>
      // @ts-expect-error — deliberately invalid wire to test runtime behaviour
      createProviderAdapter({ ...minimalOptions, wire: "unknown-wire" }),
    ).toThrow();
  });
});
