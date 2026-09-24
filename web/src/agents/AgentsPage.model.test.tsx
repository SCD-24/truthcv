// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { getAgentConfig, getAgentStatus, getProfileAnswers, getRouting, listConnections,
  triggerAgentRun } from "../api/client";
import type { AgentConfig, AgentStatus, ProfileAnswers } from "../api/types";
import { AgentsPage } from "./AgentsPage";

vi.mock("../api/client", () => ({
  getAgentConfig: vi.fn(), getAgentStatus: vi.fn(), getProfileAnswers: vi.fn(),
  getRouting: vi.fn(), listConnections: vi.fn(),
  listRuns: vi.fn().mockResolvedValue({ runs: [], total: 0, limit: 5, offset: 0 }),
  triggerAgentRun: vi.fn(), updateAgentConfig: vi.fn(), saveProfileAnswers: vi.fn(),
  getSigninQueue: vi.fn().mockResolvedValue({ sites: [] }),
}));
function makeConfig(): AgentConfig {
  return { mode: "full", enabled: true, blockedCompanies: [], runAt: ["09:00"],
    runDays: ["mon"], runTimezone: "UTC", profiles: [], jobBoards: [], targetCompanies: [],
    cooldownDays: null, cooldownDaysSameRole: null, cooldownDaysSameCompany: null,
    maxApplicationsPerRun: null, maxPostingAgeDays: null, companyBoards: [] };
}
function makeStatus(): AgentStatus {
  return { running: false, cancelling: false, lastStartedAt: null, lastFinishedAt: null,
    lastExitCode: null, lastCancelled: false };
}
function renderAgent() {
  vi.mocked(getAgentConfig).mockResolvedValue(makeConfig());
  vi.mocked(getAgentStatus).mockResolvedValue(makeStatus());
  vi.mocked(getProfileAnswers).mockResolvedValue({ phone: "", workAuthorisation: "",
    noticePeriod: "", locationPreference: "", canonicalCvAssetId: null, name: "", email: "",
    linkedin: "", github: "", website: "", workAuthorisationNote: "", requiresSponsorship: "",
    authorizedNonGermanCountry: "", languages: "", highestRelevantDegree: "", otherDegree: "",
    csDegree: "", gpa: "", gender: "", yearsOfExperience: "", currentRole: "",
    howDidYouHear: "" } as ProfileAnswers);
  return render(<MemoryRouter><AgentsPage onBack={vi.fn()} /></MemoryRouter>);
}
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("AgentsPage without routing controls", () => {
  it("keeps agent operations available without loading routing or accounts", async () => {
    renderAgent();
    expect(await screen.findByRole("slider", { name: "Agent autonomy" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Schedule" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Model" })).toBeNull();
    expect(getRouting).not.toHaveBeenCalled();
    expect(listConnections).not.toHaveBeenCalled();
  });
  it("renders an enabled Run now button when the agent is enabled", async () => {
    renderAgent();
    expect((await screen.findByRole("button", { name: /run agent now/i })).hasAttribute("disabled")).toBe(false);
  });
  it("starts a run and displays running state", async () => {
    vi.mocked(triggerAgentRun).mockResolvedValue({ started: true, running: true });
    renderAgent();
    const button = await screen.findByRole("button", { name: /run agent now/i });
    await act(async () => { fireEvent.click(button); });
    expect(triggerAgentRun).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /run agent now/i }).hasAttribute("disabled")).toBe(true);
  });
  it("shows a 503 inline error", async () => {
    vi.mocked(triggerAgentRun).mockRejectedValue(new Error("Agent service unreachable"));
    renderAgent();
    const button = await screen.findByRole("button", { name: /run agent now/i });
    await act(async () => { fireEvent.click(button); });
    expect(await screen.findByText("Agent service unreachable")).toBeTruthy();
  });
  it("clears the polling interval on unmount", async () => {
    const spy = vi.spyOn(globalThis, "clearInterval");
    const view = renderAgent();
    await screen.findByRole("button", { name: /run agent now/i });
    view.unmount();
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });
});
