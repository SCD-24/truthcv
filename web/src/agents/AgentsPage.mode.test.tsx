// @vitest-environment jsdom
/** The autonomy slider: off / semi-auto / full auto. Stubbing follows
 * AgentsPage.model.test.tsx — mock the API client module, render with jsdom. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  getAgentConfig,
  getAgentStatus,
  getProfileAnswers,
  getRouting,
  listConnectionModels,
  listConnections,
  updateAgentConfig,
} from "../api/client";
import type { AgentConfig, AgentStatus, Routing } from "../api/types";
import type { ProfileAnswers } from "../api/types";
import { AgentsPage } from "./AgentsPage";

vi.mock("../api/client", () => ({
  getAgentConfig: vi.fn(),
  getAgentStatus: vi.fn(),
  getProfileAnswers: vi.fn(),
  getRouting: vi.fn(),
  listConnections: vi.fn(),
  listConnectionModels: vi.fn(),
  triggerAgentRun: vi.fn(),
  updateAgentConfig: vi.fn(),
  saveProfileAnswers: vi.fn(),
  updateRouting: vi.fn(),
}));

function makeConfig(overrides: Partial<AgentConfig> = {}): AgentConfig {
  return {
    mode: "full",
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

/** Copied verbatim from AgentsPage.model.test.tsx — long, unchanged, and
 * already correct. */
function makeAnswers(): ProfileAnswers {
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
}

function makeRouting(overrides: Partial<Routing> = {}): Routing {
  return {
    tasks: {},
    agent: null,
    default: null,
    ...overrides,
  };
}

function makeAgentStatus(overrides: Partial<AgentStatus> = {}): AgentStatus {
  return {
    running: false,
    lastStartedAt: null,
    lastFinishedAt: null,
    lastExitCode: null,
    ...overrides,
  };
}

async function renderWithMode(mode: AgentConfig["mode"]) {
  vi.mocked(getAgentConfig).mockResolvedValue(makeConfig({ mode, enabled: mode !== "off" }));
  vi.mocked(getAgentStatus).mockResolvedValue(makeAgentStatus());
  vi.mocked(getProfileAnswers).mockResolvedValue(makeAnswers());
  vi.mocked(getRouting).mockResolvedValue(makeRouting());
  vi.mocked(listConnections).mockResolvedValue({ connections: [] } as never);
  vi.mocked(listConnectionModels).mockResolvedValue([]);
  render(<AgentsPage onBack={vi.fn()} />);
  await screen.findByRole("slider", { name: "Agent autonomy" });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AgentsPage autonomy slider", () => {
  it("sits at the stored mode and explains it", async () => {
    await renderWithMode("semi");
    expect(screen.getByRole("slider", { name: "Agent autonomy" }).getAttribute("value")).toBe("1");
    expect(screen.getByText(/You draft the cover letter and approve/)).toBeTruthy();
  });

  it("moving it writes the new mode", async () => {
    await renderWithMode("semi");
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig({ mode: "full" }));
    fireEvent.change(screen.getByRole("slider", { name: "Agent autonomy" }), {
      target: { value: "2" },
    });
    await waitFor(() => expect(updateAgentConfig).toHaveBeenCalledWith({ mode: "full" }));
  });

  it("off is reachable and explains that nothing is submitted", async () => {
    await renderWithMode("full");
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig({ mode: "off", enabled: false }));
    fireEvent.change(screen.getByRole("slider", { name: "Agent autonomy" }), {
      target: { value: "0" },
    });
    await waitFor(() => expect(updateAgentConfig).toHaveBeenCalledWith({ mode: "off" }));
    expect(await screen.findByText(/Nothing is submitted/)).toBeTruthy();
  });

  it("reverts to the previous mode when the save fails", async () => {
    await renderWithMode("semi");
    vi.mocked(updateAgentConfig).mockRejectedValue(new Error("nope"));
    fireEvent.change(screen.getByRole("slider", { name: "Agent autonomy" }), {
      target: { value: "2" },
    });
    expect(await screen.findByText("nope")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByRole("slider", { name: "Agent autonomy" }).getAttribute("value")).toBe("1"),
    );
  });
});
