import { describe, it, expect, vi, afterEach } from "vitest";
import { listDidNotPass, listRuns, getRun } from "./client";
import type { ScreeningRecord } from "./types";

function makeScreening(overrides: Partial<ScreeningRecord> = {}): ScreeningRecord {
  return {
    id: "s1",
    company: "Acme",
    role: "Engineer",
    url: "https://acme.example/jobs/1",
    screenedDate: "",
    verdict: "rejected",
    failingCriterion: "",
    reason: "",
    cooldownExpires: "",
    source: "",
    postingText: "",
    postedDate: "",
    approval: "",
    applyAttempts: 0,
    applyError: "",
    screeningBlocker: "",
    claimedByRun: "",
    claimExpiresAt: "",
    createdAt: "2024-06-01T12:00:00+00:00",
    updatedAt: "2024-06-01T12:00:00+00:00",
    ...overrides,
  } as ScreeningRecord;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("listDidNotPass", () => {
  it("excludes a record blocked at screening time even though its verdict reads rejected", async () => {
    const rejected = makeScreening({ id: "s-rejected", verdict: "rejected" });
    const blocked = makeScreening({
      id: "s-blocked",
      verdict: "",
      screeningBlocker: "unreadable",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [rejected, blocked],
      }),
    );

    const result = await listDidNotPass();

    expect(result.map((r) => r.id)).toEqual(["s-rejected"]);
  });
});

describe("listRuns / getRun", () => {
  it("returns the whole page envelope and honours limit", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ runs: [{ id: "run-1" }], total: 12, limit: 5, offset: 0 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const page = await listRuns(5);

    // The envelope is no longer unwrapped: total is what tells the caller how
    // many pages exist, and it cannot be recovered from the runs array.
    expect(page.runs).toEqual([{ id: "run-1" }]);
    expect(page.total).toBe(12);
    expect(fetchMock.mock.calls[0][0]).toContain("limit=5");
  });

  it("sends the offset when paging past the first page", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ runs: [], total: 12, limit: 5, offset: 5 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await listRuns(5, 5);

    expect(fetchMock.mock.calls[0][0]).toContain("offset=5");
  });

  it("omits both params when neither is given", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ runs: [], total: 0, limit: 50, offset: 0 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await listRuns();

    expect(fetchMock.mock.calls[0][0]).not.toContain("?");
  });

  it("fetches a single run by id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ id: "run-1", status: "completed" }),
      }),
    );

    const run = await getRun("run-1");
    expect(run.id).toBe("run-1");
  });
});
