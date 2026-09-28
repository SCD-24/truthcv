// @vitest-environment jsdom
/** `request()`'s abort handling: a caller-supplied AbortSignal must be
 * forwarded into the fetch it makes, distinct from the internal timeout
 * controller — a caller cancelling its own request must see an AbortError,
 * not the generic "took too long" timeout message. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { request } from "./client";

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.unstubAllGlobals());

describe("request() — caller abort signal", () => {
  it("rethrows an AbortError when the caller's signal aborts before the fetch settles", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("aborted", "AbortError"));
        });
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const controller = new AbortController();
    const promise = request("/api/x", { signal: controller.signal });
    controller.abort();

    await expect(promise).rejects.toMatchObject({ name: "AbortError" });
  });

  it("aborts immediately when the caller's signal is already aborted", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      return new Promise((_resolve, reject) => {
        if (init?.signal?.aborted) reject(new DOMException("aborted", "AbortError"));
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const controller = new AbortController();
    controller.abort();

    await expect(request("/api/x", { signal: controller.signal })).rejects.toMatchObject({
      name: "AbortError",
    });
  });

  it("still reports a timeout with the existing message when nothing aborts it", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const promise = request("/api/x");
    const assertion = expect(promise).rejects.toThrow(/took too long/i);
    await vi.runAllTimersAsync();
    await assertion;
    vi.useRealTimers();
  });

  it("reports a network failure with the existing message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("network down"))),
    );

    await expect(request("/api/x")).rejects.toThrow(/can't reach the server/i);
  });
});
