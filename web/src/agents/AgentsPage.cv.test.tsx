// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  getAgentConfig,
  getProfileAnswers,
  getRouting,
  listConnectionModels,
  listConnections,
} from "../api/client";
import type { AgentConfig, ConnectionList, ProfileAnswers, Routing } from "../api/types";
import { AgentsPage } from "./AgentsPage";

/** Mirrors AgentsPage.profiles.test.tsx's boundary choice — mock the API client
 * module directly and render with @testing-library/react + jsdom. */
vi.mock("../api/client", () => ({
  getAgentConfig: vi.fn(),
  // RunNowSection polls this on mount; default to idle so sibling sections'
  // tests don't have to know about it.
  getAgentStatus: vi
    .fn()
    .mockResolvedValue({ running: false, lastStartedAt: null, lastFinishedAt: null, lastExitCode: null }),
  triggerAgentRun: vi.fn(),
  getProfileAnswers: vi.fn(),
  getRouting: vi.fn(),
  listConnections: vi.fn(),
  listConnectionModels: vi.fn(),
  listRuns: vi.fn().mockResolvedValue([]),
  getSigninQueue: vi.fn().mockResolvedValue({ sites: [] }),
}));

function makeConfig(): AgentConfig {
  return {
    mode: "full",
    enabled: true,
    blockedCompanies: [],
    runAt: ["09:00"],
    runDays: ["mon"],
    profiles: [],
    targetCompanies: [],
    cooldownDays: null,
    cooldownDaysSameRole: null,
    cooldownDaysSameCompany: null,
    maxApplicationsPerRun: null,
    maxPostingAgeDays: null,
    companyBoards: [],
  };
}

function makeAnswers(overrides: Partial<ProfileAnswers> = {}): ProfileAnswers {
  return {
    phone: "",
    workAuthorisation: "",
    noticePeriod: "",
    locationPreference: "",
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
    ...overrides,
  };
}

function makeRouting(): Routing {
  return {
    tasks: {},
    agent: null,
    default: null,
  };
}

async function renderLoaded(answers: ProfileAnswers) {
  const connections: ConnectionList = { encryptionAvailable: true, connections: [] };
  vi.mocked(getAgentConfig).mockResolvedValue(makeConfig());
  vi.mocked(getProfileAnswers).mockResolvedValue(answers);
  vi.mocked(getRouting).mockResolvedValue(makeRouting());
  vi.mocked(listConnections).mockResolvedValue(connections);
  vi.mocked(listConnectionModels).mockResolvedValue([]);
  render(
    <MemoryRouter>
      <AgentsPage onBack={vi.fn()} />
    </MemoryRouter>,
  );
  await screen.findByRole("heading", { name: "Job profiles" });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AgentsPage CV section", () => {
  it("with canonicalCvAssetId set, names the file and exposes a download link", async () => {
    await renderLoaded(makeAnswers({ canonicalCvAssetId: "canonical_cv.pdf" }));

    const link = screen.getByRole("link", { name: "canonical_cv.pdf" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/api/download/canonical_cv.pdf");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noreferrer");
  });

  it("with canonicalCvAssetId null, shows a warning and no download link", async () => {
    await renderLoaded(makeAnswers({ canonicalCvAssetId: null }));

    expect(
      screen.getByText(
        "No CV is registered. The agent will skip applications rather than substitute another file.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("link", { name: /canonical_cv|\.pdf/ })).toBeNull();
  });
});
