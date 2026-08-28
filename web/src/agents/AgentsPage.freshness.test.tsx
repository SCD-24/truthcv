// @vitest-environment jsdom
/** The posting freshness window on the Agents page: renders the stored value
 * and sends it on save. Mocking follows AgentsPage.mode.test.tsx. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  getAgentConfig,
  getAgentStatus,
  getProfileAnswers,
  getRouting,
  listConnectionModels,
  listConnections,
  updateAgentConfig,
} from "../api/client";
import type { AgentConfig, AgentStatus, ProfileAnswers, Routing } from "../api/types";
import { AgentsPage } from "./AgentsPage";

vi.mock("../api/client", () => ({
  cancelAgentRun: vi.fn(),
  getAgentConfig: vi.fn(),
  getAgentStatus: vi.fn(),
  getProfileAnswers: vi.fn(),
  getRouting: vi.fn(),
  listConnections: vi.fn(),
  listConnectionModels: vi.fn(),
  listRuns: vi.fn().mockResolvedValue({ runs: [], total: 0, limit: 5, offset: 0 }),
  triggerAgentRun: vi.fn(),
  updateAgentConfig: vi.fn(),
  saveProfileAnswers: vi.fn(),
  updateRouting: vi.fn(),
  getSigninQueue: vi.fn().mockResolvedValue({ sites: [] }),
}));

const LABEL = "Only postings from the last (days)";

function makeConfig(overrides: Partial<AgentConfig> = {}): AgentConfig {
  return {
    mode: "full",
    enabled: true,
    blockedCompanies: [],
    runAt: ["09:00"],
    runDays: ["mon"],
    profiles: [],
    jobBoards: [],
    targetCompanies: [],
    cooldownDays: null,
    cooldownDaysSameRole: null,
    cooldownDaysSameCompany: null,
    maxApplicationsPerRun: null,
    maxPostingAgeDays: null,
    companyBoards: [],
    ...overrides,
  };
}

function makeAnswers(): ProfileAnswers {
  return {
    phone: "", workAuthorisation: "", noticePeriod: "", locationPreference: "",
    canonicalCvAssetId: null, name: "", email: "", linkedin: "", github: "",
    website: "", workAuthorisationNote: "", requiresSponsorship: "",
    authorizedNonGermanCountry: "", languages: "", highestRelevantDegree: "",
    otherDegree: "", csDegree: "", gpa: "", gender: "", yearsOfExperience: "",
    currentRole: "", howDidYouHear: "",
  };
}

function makeRouting(): Routing {
  return { tasks: {}, agent: null, default: null };
}

function makeStatus(): AgentStatus {
  return {
    running: false, cancelling: false, lastStartedAt: null,
    lastFinishedAt: null, lastExitCode: null, lastCancelled: false,
  };
}

async function renderWith(config: AgentConfig) {
  vi.mocked(getAgentConfig).mockResolvedValue(config);
  vi.mocked(getAgentStatus).mockResolvedValue(makeStatus());
  vi.mocked(getProfileAnswers).mockResolvedValue(makeAnswers());
  vi.mocked(getRouting).mockResolvedValue(makeRouting());
  vi.mocked(listConnections).mockResolvedValue({ connections: [] } as never);
  vi.mocked(listConnectionModels).mockResolvedValue([]);
  render(
    <MemoryRouter>
      <AgentsPage onBack={vi.fn()} />
    </MemoryRouter>,
  );
  await screen.findByRole("slider", { name: "Agent autonomy" });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("posting freshness window", () => {
  it("shows the stored window", async () => {
    await renderWith(makeConfig({ maxPostingAgeDays: 14 }));
    const field = (await screen.findByLabelText(LABEL)) as HTMLInputElement;
    expect(field.value).toBe("14");
  });

  it("shows an empty box when unset", async () => {
    await renderWith(makeConfig({ maxPostingAgeDays: null }));
    const field = (await screen.findByLabelText(LABEL)) as HTMLInputElement;
    expect(field.value).toBe("");
  });

  it("sends the edited window on save", async () => {
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig({ maxPostingAgeDays: 7 }));
    await renderWith(makeConfig({ maxPostingAgeDays: null }));

    fireEvent.change(await screen.findByLabelText(LABEL), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Save profiles" }));

    await waitFor(() => expect(vi.mocked(updateAgentConfig)).toHaveBeenCalled());
    const body = vi.mocked(updateAgentConfig).mock.calls[0][0];
    expect(body.maxPostingAgeDays).toBe(7);
  });

  it("sends 0 as 0, not as a cleared field", async () => {
    // 0 is the way to disable the window; it must not be coerced to null.
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig({ maxPostingAgeDays: 0 }));
    await renderWith(makeConfig({ maxPostingAgeDays: 30 }));

    fireEvent.change(await screen.findByLabelText(LABEL), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Save profiles" }));

    await waitFor(() => expect(vi.mocked(updateAgentConfig)).toHaveBeenCalled());
    expect(vi.mocked(updateAgentConfig).mock.calls[0][0].maxPostingAgeDays).toBe(0);
  });
});
