import { describe, it, expect, vi, afterEach } from "vitest";
import { listApplicationsPage } from "./client";
import type { Application } from "./types";

function makeApp(overrides: Partial<Application> = {}): Application {
  return {
    id: "a1",
    company: "Acme",
    website: "",
    applicationUrl: "",
    submitted: false,
    submissionType: "",
    reachedOut: false,
    toWho: "",
    responseReceived: false,
    method: "",
    posting: "",
    applicationDate: "",
    status: "",
    notes: "",
    cvDocument: null,
    coverLetterDocument: null,
    createdAt: "",
    updatedAt: "",
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("listApplicationsPage", () => {
  it("returns the whole page envelope", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        applications: [makeApp({ id: "a1" })],
        total: 12,
        limit: 5,
        offset: 0,
        sort: "date",
        direction: "desc",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const page = await listApplicationsPage({});

    expect(page.applications).toHaveLength(1);
    expect(page.total).toBe(12);
    expect(page.limit).toBe(5);
    expect(page.offset).toBe(0);
    expect(page.sort).toBe("date");
    expect(page.direction).toBe("desc");
  });

  it("sends limit, offset, sort, and direction in query string", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        applications: [],
        total: 0,
        limit: 25,
        offset: 25,
        sort: "company",
        direction: "asc",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await listApplicationsPage({ limit: 25, offset: 25, sort: "company", direction: "asc" });

    const url = fetchMock.mock.calls[0][0];
    expect(url).toContain("/api/applications/page");
    expect(url).toContain("limit=25");
    expect(url).toContain("offset=25");
    expect(url).toContain("sort=company");
    expect(url).toContain("direction=asc");
  });

  it("omits unspecified parameters", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        applications: [],
        total: 0,
        limit: 25,
        offset: 0,
        sort: "date",
        direction: "desc",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await listApplicationsPage({});

    const url = fetchMock.mock.calls[0][0];
    expect(url).toBe("/api/applications/page");
  });

  it("builds correct query string with partial options", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        applications: [],
        total: 0,
        limit: 10,
        offset: 5,
        sort: "status",
        direction: "asc",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await listApplicationsPage({ limit: 10, offset: 5 });

    const url = fetchMock.mock.calls[0][0];
    expect(url).toContain("limit=10");
    expect(url).toContain("offset=5");
    expect(url).not.toContain("sort=");
    expect(url).not.toContain("direction=");
  });
});
