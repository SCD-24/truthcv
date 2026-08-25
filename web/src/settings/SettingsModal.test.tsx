// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  getProfileAnswers,
  getRouting,
  listConnections,
  saveProfileAnswers,
} from "../api/client";
import type { ConnectionList, ProfileAnswers, Routing } from "../api/types";
import { SettingsModal } from "./SettingsModal";
import { WizardProvider } from "../wizard/store";

/**
 * This file mixes two boundary choices: the profile-answers tests exercise
 * API client functions by stubbing globalThis.fetch, unrelated to
 * SettingsModal's own rendering. The SettingsModal render tests below mock
 * the API client module directly (mirroring AccountsSection.test.tsx),
 * keeping the rest of the client's exports as their real fetch-backed
 * implementations via importOriginal so the fetch-stub tests keep working
 * unmodified.
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

/** Pins the plan's explicit doneWhen: profile answers round-trip through the
 * client to the real routes with the right method and a partial-merge body. */
describe("profile answers round-trip", () => {
  it("getProfileAnswers requests /api/profile/answers with no method override and returns the body", async () => {
    const fresh: ProfileAnswers = {
      phone: "555-0100",
      workAuthorisation: "Authorised to work",
      noticePeriod: "2 weeks",
      locationPreference: "Remote",
      canonicalCvAssetId: null,
      name: "",
      email: "",
      linkedin: "",
      github: "",
      website: "",
      workAuthorisationNote: "",
  requiresSponsorship: "",
      authorizedNonGermanCountry: "",
      languages: "",
      highestRelevantDegree: "",
      otherDegree: "",
      csDegree: "",
      gpa: "",
      gender: "",
      yearsOfExperience: "",
      currentRole: "",
      howDidYouHear: "",
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
      workAuthorisationNote: "",
      workAuthorisation: "Authorised to work",
      noticePeriod: "2 weeks",
      locationPreference: "Remote",
      canonicalCvAssetId: null,
      name: "",
      email: "",
      linkedin: "",
      github: "",
      website: "",
      requiresSponsorship: "",
      authorizedNonGermanCountry: "",
      languages: "",
      highestRelevantDegree: "",
      otherDegree: "",
      csDegree: "",
      gpa: "",
      gender: "",
      yearsOfExperience: "",
      currentRole: "",
      howDidYouHear: "",
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

    render(
      <WizardProvider>
        <SettingsModal onClose={vi.fn()} />
      </WizardProvider>,
    );

    expect(await screen.findByText("Accounts")).toBeTruthy();
    expect(screen.getByText("Default model")).toBeTruthy();
    expect(screen.getByText("Task models")).toBeTruthy();
    expect(screen.getAllByText("Claude").length).toBeGreaterThan(0);
  });
});
