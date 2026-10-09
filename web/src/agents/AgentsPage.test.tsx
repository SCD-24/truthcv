// @vitest-environment jsdom
/** Run-now status polling: no overlapping request while one is pending. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import {
  getAgentConfig,
  getAgentStatus,
  getProfileAnswers,
  listRuns,
} from "../api/client";
import type { AgentConfig, AgentStatus } from "../api/types";
import { AgentsPage } from "./AgentsPage";

vi.mock("../api/client", () => ({
  getAgentConfig: vi.fn(),
  getProfileAnswers: vi.fn(),
  getAgentStatus: vi.fn(),
  cancelAgentRun: vi.fn(),
  triggerAgentRun: vi.fn(),
  updateAgentConfig: vi.fn(),
  saveProfileAnswers: vi.fn(),
  listRuns: vi.fn(),
}));

function makeConfig(): AgentConfig {
  return {
    mode: "off",
    enabled: false,
    blockedCompanies: [],
    runAt: [],
    runDays: [],
    runTimezone: "UTC",
    profiles: [],
    jobBoards: [],
    targetCompanies: [],
    cooldownDays: null,
    cooldownDaysSameRole: null,
    cooldownDaysSameCompany: null,
    maxApplicationsPerRun: null,
    maxPostingAgeDays: null,
    dorkRecency: "d",
    companyBoards: [],
  };
}

function makeStatus(overrides: Partial<AgentStatus> = {}): AgentStatus {
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

beforeEach(() => {
  vi.mocked(getAgentConfig).mockResolvedValue(makeConfig());
  vi.mocked(getProfileAnswers).mockResolvedValue({} as never);
  vi.mocked(listRuns).mockResolvedValue({ runs: [], total: 0, offset: 0 } as never);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("AgentsPage run-now status polling", () => {
  it("does not issue a second status request while one is still pending", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const deferred: { resolve?: (s: AgentStatus) => void } = {};
    let calls = 0;
    vi.mocked(getAgentStatus).mockImplementation(() => {
      calls += 1;
      if (calls === 1) {
        return new Promise<AgentStatus>((resolve) => {
          deferred.resolve = resolve;
        });
      }
      return Promise.resolve(makeStatus());
    });

    render(
      <BrowserRouter>
        <AgentsPage />
      </BrowserRouter>,
    );

    await vi.waitFor(() => expect(calls).toBe(1));

    // The next poll would be due at STATUS_POLL_IDLE_MS, but the first
    // request is still outstanding — no second call must fire.
    await vi.advanceTimersByTimeAsync(20_000);
    expect(calls).toBe(1);

    deferred.resolve?.(makeStatus());
    // The next poll is scheduled STATUS_POLL_IDLE_MS after this one settles;
    // advance fake time through it before waiting for the second call.
    await vi.advanceTimersByTimeAsync(10_000);
    await vi.waitFor(() => expect(calls).toBe(2));

    vi.useRealTimers();
  });

  it("skips the poll while the tab is hidden and polls immediately once shown", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(getAgentStatus).mockResolvedValue(makeStatus());

    render(
      <BrowserRouter>
        <AgentsPage />
      </BrowserRouter>,
    );

    await vi.waitFor(() => expect(getAgentStatus).toHaveBeenCalledTimes(1));

    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    await vi.advanceTimersByTimeAsync(30_000);
    // Still just the one initial call — hidden tab skipped its polls.
    expect(getAgentStatus).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    document.dispatchEvent(new Event("visibilitychange"));

    await vi.waitFor(() => expect(getAgentStatus).toHaveBeenCalledTimes(2));

    vi.useRealTimers();
  });
});
