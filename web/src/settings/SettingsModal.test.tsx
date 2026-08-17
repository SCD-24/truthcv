// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  deleteScreening,
  getCooldown,
  getProfileAnswers,
  getRouting,
  listConnections,
  listScreenings,
  saveProfileAnswers,
} from "../api/client";
import type {
  ConnectionList,
  CooldownStatus,
  ProfileAnswers,
  Routing,
  ScreeningRecord,
} from "../api/types";
import { isCooldownActive } from "./cooldown";
import { lastAgentActivity } from "./agentActivity";
import { SettingsModal } from "./SettingsModal";

/**
 * This file mixes two boundary choices: most tests exercise pure logic
 * (isCooldownActive, lastAgentActivity) and API client functions by stubbing
 * globalThis.fetch, unrelated to SettingsModal's own rendering. The
 * SettingsModal render tests below mock the API client module directly
 * (mirroring AccountsSection.test.tsx), keeping the rest of the client's
 * exports as their real fetch-backed implementations via importOriginal so
 * the fetch-stub tests keep working unmodified.
 */
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    listConnections: vi.fn(),
    getRouting: vi.fn(),
  };
});

/** Build a fetch Response stub with only the members request<T>() reads
 * (ok, status, json()) — enough to drive the client without a real DOM/Fetch
 * implementation. */
function jsonResponse<T>(body: T, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

/** A stub for a 204 No Content response — request<T>() must resolve
 * `undefined` for these without ever calling .json(). */
function noContentResponse(status = 204): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      throw new Error("204 response body should never be read");
    },
  } as unknown as Response;
}

let originalFetch: typeof fetch;
let fetchMock: Mock<typeof fetch>;

beforeEach(() => {
  originalFetch = globalThis.fetch;
  fetchMock = vi.fn<typeof fetch>();
  globalThis.fetch = fetchMock;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

/** Pins the cooldown predicate's contract: only a parseable, still-future
 * expiry counts as active. A malformed or missing record must read as NOT
 * in cooldown — an agent bug that writes a bad timestamp must never
 * silently and permanently block a company. */
describe("isCooldownActive", () => {
  const now = new Date("2024-06-15T00:00:00Z");

  it("is active when the expiry is in the future", () => {
    expect(isCooldownActive("2024-06-20T00:00:00Z", now)).toBe(true);
  });

  it("is not active when the expiry is in the past", () => {
    expect(isCooldownActive("2024-06-01T00:00:00Z", now)).toBe(false);
  });

  it("is not active for an empty string (no cooldown recorded)", () => {
    expect(isCooldownActive("", now)).toBe(false);
  });

  it("is not active for a garbage/unparseable string — a bad record must never silently block a company forever", () => {
    expect(isCooldownActive("not-a-real-date", now)).toBe(false);
  });

  it("is not active when the expiry is exactly now", () => {
    expect(isCooldownActive("2024-06-15T00:00:00Z", now)).toBe(false);
  });
});

/** Build a ScreeningRecord fixture shaped exactly like the ones the backend
 * emits (screening/model.py's Screening dataclass, serialised camelCase per
 * api/schemas.py), so these tests exercise realistic records rather than a
 * loose partial cast. */
function makeScreening(overrides: Partial<ScreeningRecord> = {}): ScreeningRecord {
  return {
    id: "a1b2c3d4e5f6",
    company: "Acme Corp",
    role: "Engineer",
    url: "https://acme.example/careers/123",
    screenedDate: "2024-06-01T12:00:00+00:00",
    verdict: "rejected",
    failingCriterion: "salary",
    reason: "Salary below stated minimum.",
    cooldownExpires: "2024-09-01T12:00:00+00:00",
    source: "agent",
    createdAt: "2024-06-01T12:00:00+00:00",
    updatedAt: "2024-06-01T12:00:00+00:00",
    ...overrides,
  };
}

/** Pins the "last activity" derivation: newest usable date wins, with a
 * fallback and null-safety contract so a gap in the ledger reads as "hasn't
 * run yet" rather than showing a wrong or stale date. */
describe("lastAgentActivity", () => {
  it("picks the newest record's date out of several", () => {
    const screenings = [
      makeScreening({ id: "s1", screenedDate: "2024-06-01T00:00:00+00:00" }),
      makeScreening({ id: "s2", screenedDate: "2024-06-10T00:00:00+00:00" }),
      makeScreening({ id: "s3", screenedDate: "2024-06-05T00:00:00+00:00" }),
    ];
    expect(lastAgentActivity(screenings)).toBe("2024-06-10T00:00:00+00:00");
  });

  it("falls back to createdAt when screenedDate is empty", () => {
    const screenings = [
      makeScreening({ screenedDate: "", createdAt: "2024-06-05T00:00:00+00:00" }),
    ];
    expect(lastAgentActivity(screenings)).toBe("2024-06-05T00:00:00+00:00");
  });

  it("returns null for an empty array", () => {
    expect(lastAgentActivity([])).toBeNull();
  });

  it("returns null when no record's date parses", () => {
    const screenings = [
      makeScreening({ screenedDate: "not-a-date", createdAt: "" }),
    ];
    expect(lastAgentActivity(screenings)).toBeNull();
  });
});

/** Pins the plan's explicit doneWhen: profile answers round-trip through the
 * client to the real routes with the right method and a partial-merge body. */
describe("profile answers round-trip", () => {
  it("getProfileAnswers requests /api/profile/answers with no method override and returns the body", async () => {
    const fresh: ProfileAnswers = {
      phone: "555-0100",
      workAuthorisation: "Authorised to work",
      salaryExpectation: "$120k",
      noticePeriod: "2 weeks",
      locationPreference: "Remote",
      canonicalCvAssetId: null,
    };
    fetchMock.mockResolvedValueOnce(jsonResponse(fresh));

    const result = await getProfileAnswers();

    expect(fetchMock.mock.calls).toHaveLength(1);
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/profile/answers");
    expect(init?.method).toBeUndefined();
    expect(result).toEqual(fresh);
  });

  it("saveProfileAnswers PUTs only the passed keys and returns the response body as the fresh values", async () => {
    const fresh: ProfileAnswers = {
      phone: "555-0199",
      workAuthorisation: "Authorised to work",
      salaryExpectation: "$120k",
      noticePeriod: "2 weeks",
      locationPreference: "Remote",
      canonicalCvAssetId: null,
    };
    fetchMock.mockResolvedValueOnce(jsonResponse(fresh));

    const result = await saveProfileAnswers({ phone: "555-0199" });

    expect(fetchMock.mock.calls).toHaveLength(1);
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/profile/answers");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(init?.body as string)).toEqual({ phone: "555-0199" });
    // The response body — not the request payload — is what's returned.
    expect(result).toEqual(fresh);
  });
});

/** Pins the screening-list panel's wiring: list/delete hit the right routes,
 * delete's id is percent-encoded, a 204 delete resolves without throwing,
 * and getCooldown's query string carries company (always) and role (only
 * when supplied). */
describe("screening list", () => {
  it("listScreenings GETs /api/screenings and returns the records", async () => {
    const records = [makeScreening({ id: "s1" }), makeScreening({ id: "s2" })];
    fetchMock.mockResolvedValueOnce(jsonResponse(records));

    const result = await listScreenings();

    const [path] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/screenings");
    expect(result).toEqual(records);
  });

  it("deleteScreening DELETEs /api/screenings/<percent-encoded id> and resolves on a 204 with no body", async () => {
    fetchMock.mockResolvedValueOnce(noContentResponse());

    const result = await deleteScreening("abc 123/x");

    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe(`/api/screenings/${encodeURIComponent("abc 123/x")}`);
    expect(init?.method).toBe("DELETE");
    expect(result).toBeUndefined();
  });

  it("getCooldown puts company and role in the query string", async () => {
    const status: CooldownStatus = { inCooldown: true, expires: "2024-09-01T12:00:00+00:00" };
    fetchMock.mockResolvedValueOnce(jsonResponse(status));

    const result = await getCooldown("Acme", "Engineer");

    const [path] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/cooldown?company=Acme&role=Engineer");
    expect(result).toEqual(status);
  });

  it("getCooldown omits role entirely when not supplied", async () => {
    const status: CooldownStatus = { inCooldown: false, expires: null };
    fetchMock.mockResolvedValueOnce(jsonResponse(status));

    await getCooldown("Acme");

    const [path] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/cooldown?company=Acme");
  });
});

/** Pins the rewired modal's own contract: it loads connections + routing on
 * open and renders both the Accounts and Default model sections from them,
 * rather than the old single Provider panel. */
describe("SettingsModal", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("loads connections + routing on open and renders both sections", async () => {
    const list: ConnectionList = {
      encryptionAvailable: true,
      connections: [
        {
          provider: "claude",
          label: "Claude",
          modes: ["subscription"],
          subscriptionConnected: true,
          apiKeyConnected: false,
          authMode: "subscription",
          expiresAt: null,
          connectedAt: null,
        },
      ],
    };
    const routing: Routing = { tasks: {}, agent: null, default: null };
    vi.mocked(listConnections).mockResolvedValueOnce(list);
    vi.mocked(getRouting).mockResolvedValueOnce(routing);

    render(<SettingsModal onClose={vi.fn()} />);

    expect(await screen.findByText("Accounts")).toBeTruthy();
    expect(screen.getByText("Default model")).toBeTruthy();
    expect(screen.getByText("Task models")).toBeTruthy();
    expect(screen.getAllByText("Claude").length).toBeGreaterThan(0);
  });
});
