/** request()'s 422 handling: a guardrail block carries structured
 * blockedClaims in its `detail` object and must surface as a
 * GuardrailBlockedError so callers can offer the approve/deny UI, while an
 * ordinary 422 (string detail) stays a plain Error. These run against the real,
 * unmocked request()/generateScreeningLetter in client.ts — fetch is stubbed
 * the same way approvals.client.test.ts stubs it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { generateScreeningLetter, GuardrailBlockedError } from "./client";

function stubFetchError(status: number, body: unknown) {
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

describe("generateScreeningLetter — guardrail block detection", () => {
  it("a 422 with blockedClaims in detail rejects with GuardrailBlockedError", async () => {
    stubFetchError(422, {
      detail: {
        message: "blocked",
        blockedClaims: [{ claimId: "c1", experienceId: "letter", text: "x", tokens: ["x"] }],
        paragraphs: [{ text: "p" }],
        blockedReason: "",
      },
    });
    await expect(generateScreeningLetter("s1")).rejects.toBeInstanceOf(GuardrailBlockedError);
  });

  it("a 422 with a string detail still rejects with a plain Error, not GuardrailBlockedError", async () => {
    stubFetchError(422, { detail: "Something went wrong." });
    const err = await generateScreeningLetter("s1").catch((e) => e);
    expect(err).not.toBeInstanceOf(GuardrailBlockedError);
    expect(err.message).toContain("Something went wrong");
  });
});
