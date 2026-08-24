/** The approval writers send a JSON body with the header that makes it JSON.
 *
 * Without `Content-Type: application/json` the browser labels a string body
 * text/plain, FastAPI cannot parse it into the request model, and every call
 * fails with 422 "Input should be a valid dictionary or object to extract
 * fields from". The page tests mock this module wholesale, so nothing else
 * exercises the actual request.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  bulkSetApproval,
  generateScreeningLetter,
  getScreeningLetter,
  saveScreeningLetter,
  setScreeningApproval,
  setScreeningRole,
  setScreeningUrl,
} from "./client";

function stubFetch(payload: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function stubFetchError(status: number, detail: string) {
  const body = { detail };
  const fetchMock = vi.fn().mockResolvedValue({
    ok: false,
    status,
    headers: { get: () => "application/json" },
    json: async () => body,
    text: async () => JSON.stringify(body),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.unstubAllGlobals());

describe("approval writers", () => {
  it("setScreeningApproval PATCHes JSON with the JSON content type", async () => {
    const fetchMock = stubFetch({ id: "s1", approval: "rejected" });
    await setScreeningApproval("s1", "rejected");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/screenings/s1");
    expect(init.method).toBe("PATCH");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ approval: "rejected" });
  });

  it("bulkSetApproval PATCHes JSON with the JSON content type", async () => {
    const fetchMock = stubFetch({ results: [] });
    await bulkSetApproval(["a", "b"], "approved");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/screenings/approvals");
    expect(init.method).toBe("PATCH");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ ids: ["a", "b"], approval: "approved" });
  });

  it("setScreeningUrl PATCHes JSON with the JSON content type", async () => {
    const fetchMock = stubFetch({ id: "s1", url: "https://x.example/job" });
    await setScreeningUrl("s1", "https://x.example/job");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/screenings/s1");
    expect(init.method).toBe("PATCH");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ url: "https://x.example/job" });
  });

  it("setScreeningRole PATCHes JSON with the JSON content type", async () => {
    const fetchMock = stubFetch({ id: "s1", role: "Staff Engineer" });
    await setScreeningRole("s1", "Staff Engineer");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/screenings/s1");
    expect(init.method).toBe("PATCH");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ role: "Staff Engineer" });
  });

  it("generateScreeningLetter POSTs JSON with the JSON content type", async () => {
    const fetchMock = stubFetch({ text: "Dear team,", source: "generated" });
    await generateScreeningLetter("s1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/screenings/s1/letter");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ force: false });
  });

  it("saveScreeningLetter PUTs the text verbatim", async () => {
    const fetchMock = stubFetch({ text: "Mine.", source: "operator" });
    await saveScreeningLetter("s1", "Mine.");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/screenings/s1/letter");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ text: "Mine." });
  });
});

// getScreeningLetter tells "no draft yet" apart from a real failure by
// matching the server's exact 404 detail string (see the comment at its
// call site in client.ts) — request() throws a plain Error with no status
// attached, so the string is all it has to go on. These pin that match so
// a wording change on either end fails loudly instead of turning every
// letter panel into an error state.
describe("getScreeningLetter — 404 detail matching", () => {
  it("resolves to null when the 404 detail is exactly the no-draft-yet message", async () => {
    stubFetchError(404, "No cover letter drafted yet.");
    await expect(getScreeningLetter("s1")).resolves.toBeNull();
  });

  it("rejects on a non-404 failure instead of treating it as no draft", async () => {
    stubFetchError(500, "Database unavailable.");
    await expect(getScreeningLetter("s1")).rejects.toThrow("Database unavailable.");
  });
});
