// @vitest-environment jsdom
/** The Cancel control on "Run now": visible only while a run is in progress,
 * and reporting a cancelled run as cancelled rather than as a failed exit.
 * Mocking follows AgentsPage.mode.test.tsx. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  cancelAgentRun,
  getAgentConfig,
  getAgentStatus,
  getProfileAnswers,
  getRouting,
  listConnectionModels,
  listConnections,
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
  };
}

function makeRouting(): Routing {
  return { tasks: {}, agent: null, default: null };
}

function makeAgentStatus(overrides: Partial<AgentStatus> = {}): AgentStatus {
  return {
    running: false,
    cancelling: false,
    lastStartedAt: null,
    lastFinishedAt: null,
    lastExitCode: null,
    lastCancelled: false,
    ...overrides,
  };
}

async function renderWithStatus(status: AgentStatus) {
  vi.mocked(getAgentConfig).mockResolvedValue(makeConfig());
  vi.mocked(getAgentStatus).mockResolvedValue(status);
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

describe("Run now cancel control", () => {
  it("offers no cancel while the agent is idle", async () => {
    await renderWithStatus(makeAgentStatus({ running: false }));
    expect(screen.queryByRole("button", { name: "Cancel agent run" })).toBeNull();
  });

  it("offers cancel while a run is in progress", async () => {
    await renderWithStatus(makeAgentStatus({ running: true }));
    const button = await screen.findByRole("button", { name: "Cancel agent run" });
    expect(button).toBeTruthy();
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });

  it("calls the cancel endpoint and shows the run stopping", async () => {
    vi.mocked(cancelAgentRun).mockResolvedValue({ cancelled: true, running: true });
    await renderWithStatus(makeAgentStatus({ running: true }));

    const button = await screen.findByRole("button", { name: "Cancel agent run" });
    fireEvent.click(button);

    expect(vi.mocked(cancelAgentRun)).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByText("Stopping…")).toBeTruthy());
    // Disabled while stopping so a second click cannot escalate the kill twice.
    const stopping = screen.getByRole("button", { name: "Cancel agent run" });
    expect((stopping as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows a run the supervisor is already stopping as stopping", async () => {
    // Covers a reload mid-cancel: local state is gone, the supervisor's is not.
    await renderWithStatus(makeAgentStatus({ running: true, cancelling: true }));
    await waitFor(() => expect(screen.getByText("Stopping…")).toBeTruthy());
  });

  it("surfaces an unreachable agent instead of a stuck Stopping state", async () => {
    vi.mocked(cancelAgentRun).mockRejectedValue(new Error("Agent service unreachable"));
    await renderWithStatus(makeAgentStatus({ running: true }));

    fireEvent.click(await screen.findByRole("button", { name: "Cancel agent run" }));

    await waitFor(() => expect(screen.getByText("Agent service unreachable")).toBeTruthy());
    expect(screen.queryByText("Stopping…")).toBeNull();
  });

  it("reports a cancelled run as cancelled, not as a failed exit", async () => {
    await renderWithStatus(
      makeAgentStatus({
        running: false,
        lastFinishedAt: "2026-08-24T17:40:00.000Z",
        lastExitCode: 143,
        lastCancelled: true,
      }),
    );
    await waitFor(() => expect(screen.getByText(/Last run cancelled at/)).toBeTruthy());
    expect(screen.queryByText(/exit/)).toBeNull();
  });

  it("still reports a genuinely failed run's exit code", async () => {
    await renderWithStatus(
      makeAgentStatus({
        running: false,
        lastFinishedAt: "2026-08-24T15:02:57.000Z",
        lastExitCode: 1,
        lastCancelled: false,
      }),
    );
    await waitFor(() => expect(screen.getByText(/Last run finished at/)).toBeTruthy());
    expect(screen.getByText(/exit/)).toBeTruthy();
  });
});

describe("polling lifecycle", () => {
  it("installs no interval after unmount when a cancel resolves late", async () => {
    // The leak: setPoll ran from the cancel's async continuation after cleanup
    // had already cleared the interval, so the new one was unreachable and
    // polled for the rest of the session.
    vi.useFakeTimers();
    try {
      let resolveCancel: (v: unknown) => void = () => {};
      vi.mocked(cancelAgentRun).mockReturnValue(
        new Promise((res) => {
          resolveCancel = res;
        }) as never,
      );
      vi.mocked(getAgentConfig).mockResolvedValue(makeConfig());
      vi.mocked(getAgentStatus).mockResolvedValue(makeAgentStatus({ running: true }));
      vi.mocked(getProfileAnswers).mockResolvedValue(makeAnswers());
      vi.mocked(getRouting).mockResolvedValue(makeRouting());
      vi.mocked(listConnections).mockResolvedValue({ connections: [] } as never);
      vi.mocked(listConnectionModels).mockResolvedValue([]);

      const { unmount } = render(<AgentsPage onBack={vi.fn()} />);
      await vi.waitFor(() =>
        expect(screen.getByRole("button", { name: "Cancel agent run" })).toBeTruthy(),
      );
      fireEvent.click(screen.getByRole("button", { name: "Cancel agent run" }));

      unmount();
      const callsAtUnmount = vi.mocked(getAgentStatus).mock.calls.length;

      resolveCancel({ cancelled: true, running: true });
      await Promise.resolve();
      await Promise.resolve();
      vi.advanceTimersByTime(30_000);

      expect(vi.mocked(getAgentStatus).mock.calls.length).toBe(callsAtUnmount);
    } finally {
      vi.useRealTimers();
    }
  });
});
