// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  getAgentConfig,
  getProfileAnswers,
  getRouting,
  listConnectionModels,
  listConnections,
  listScreenings,
  updateAgentConfig,
} from "../api/client";
import type { AgentConfig, ConnectionList, JobProfile, ProfileAnswers, Routing } from "../api/types";
import { AgentsPage } from "./AgentsPage";

/** Mirrors AgentsPage.model.test.tsx's boundary choice — mock the API client
 * module directly and render with @testing-library/react + jsdom. */
vi.mock("../api/client", () => ({
  getAgentConfig: vi.fn(),
  getProfileAnswers: vi.fn(),
  listScreenings: vi.fn(),
  getRouting: vi.fn(),
  listConnections: vi.fn(),
  listConnectionModels: vi.fn(),
  updateAgentConfig: vi.fn(),
  saveProfileAnswers: vi.fn(),
  deleteScreening: vi.fn(),
  updateRouting: vi.fn(),
}));

function makeConfig(overrides: Partial<AgentConfig> = {}): AgentConfig {
  return {
    enabled: true,
    blockedCompanies: [],
    runAt: ["09:00"],
    runDays: ["mon"],
    profiles: [],
    targetCompanies: [],
    cooldownDays: null,
    maxApplicationsPerRun: null,
    companyBoards: [],
    ...overrides,
  };
}

function makeProfile(overrides: Partial<JobProfile> = {}): JobProfile {
  return {
    name: "",
    enabled: true,
    keywords: [],
    locations: [],
    preferredSources: [],
    remoteModel: null,
    employmentCountry: null,
    eorAllowed: null,
    requireEntityVerification: true,
    salaryFloor: null,
    salaryAskMin: null,
    salaryAskMax: null,
    workingLanguage: null,
    glassdoorMin: null,
    glassdoorMinReviews: null,
    acceptedRoleTypes: [],
    rejectedRoleTypes: [],
    ...overrides,
  };
}

function makeAnswers(): ProfileAnswers {
  return {
    phone: "",
    workAuthorisation: "",
    salaryExpectation: "",
    noticePeriod: "",
    locationPreference: "",
    canonicalCvAssetId: null,
  };
}

function makeRouting(overrides: Partial<Routing> = {}): Routing {
  return {
    tasks: {},
    agent: null,
    default: null,
    ...overrides,
  };
}

async function renderLoaded(config: AgentConfig) {
  const connections: ConnectionList = { encryptionAvailable: true, connections: [] };
  vi.mocked(getAgentConfig).mockResolvedValue(config);
  vi.mocked(getProfileAnswers).mockResolvedValue(makeAnswers());
  vi.mocked(listScreenings).mockResolvedValue([]);
  vi.mocked(getRouting).mockResolvedValue(makeRouting());
  vi.mocked(listConnections).mockResolvedValue(connections);
  vi.mocked(listConnectionModels).mockResolvedValue([]);
  render(<AgentsPage onBack={vi.fn()} />);
  await screen.findByRole("heading", { name: "Job profiles" });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AgentsPage profiles section", () => {
  it("round-trips a comma-delimited field: typed 'a, b' saves as ['a','b'] and renders back as 'a, b'", async () => {
    await renderLoaded(makeConfig());

    fireEvent.click(screen.getByRole("button", { name: "Add profile" }));
    const keywords = screen.getByLabelText("Keywords");
    fireEvent.change(keywords, { target: { value: "a, b" } });

    vi.mocked(updateAgentConfig).mockResolvedValueOnce(
      makeConfig({ profiles: [makeProfile({ keywords: ["a", "b"] })] }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save profiles" }));

    await vi.waitFor(() => {
      expect((screen.getByLabelText("Keywords") as HTMLInputElement).value).toBe("a, b");
    });
  });

  it("leaves a blank multi-item/numeric field as its off value ([] / null), not [\"\"] or 0", async () => {
    await renderLoaded(makeConfig());

    fireEvent.click(screen.getByRole("button", { name: "Add profile" }));
    // Keywords and Salary floor are left blank.
    vi.mocked(updateAgentConfig).mockResolvedValueOnce(
      makeConfig({ profiles: [makeProfile()] }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save profiles" }));

    await vi.waitFor(() => expect(updateAgentConfig).toHaveBeenCalled());
    const body = vi.mocked(updateAgentConfig).mock.calls[0][0];
    expect(body.profiles?.[0]?.keywords).toEqual([]);
    expect(body.profiles?.[0]?.salaryFloor).toBeNull();
  });

  it("saving profiles sends only profile-shaped keys, never the schedule's or blocklist's fields", async () => {
    await renderLoaded(makeConfig());

    vi.mocked(updateAgentConfig).mockResolvedValueOnce(makeConfig());
    fireEvent.click(screen.getByRole("button", { name: "Save profiles" }));

    await vi.waitFor(() => expect(updateAgentConfig).toHaveBeenCalled());
    const body = vi.mocked(updateAgentConfig).mock.calls[0][0];
    expect(Object.keys(body).sort()).toEqual(
      ["cooldownDays", "maxApplicationsPerRun", "profiles"].sort(),
    );
    expect(body).not.toHaveProperty("runAt");
    expect(body).not.toHaveProperty("runDays");
    expect(body).not.toHaveProperty("blockedCompanies");

    // The other sections are still on the page, untouched by the profiles save.
    expect(screen.getByRole("heading", { name: "Schedule" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Blocked companies" })).toBeTruthy();
  });
});
