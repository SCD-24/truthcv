// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { RecentRunsSection } from "./AgentsPage";
import * as client from "../api/client";
import type { RunRecord } from "../api/types";

function makeRun(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: "run-1",
    startedAt: "2024-06-01T12:00:00+00:00",
    finishedAt: "2024-06-01T12:05:00+00:00",
    status: "completed",
    trigger: "scheduled",
    applyCap: 5,
    postingsSeen: 10,
    screeningsRecorded: 8,
    blockedCount: 1,
    applicationsSubmitted: 3,
    overCapWrites: 0,
    stoppedReason: "",
    note: "",
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("RecentRunsSection", () => {
  it("renders coverage counters and stopped_reason for a finished run", async () => {
    vi.spyOn(client, "listRuns").mockResolvedValue([
      makeRun({
        id: "run-finished",
        status: "completed",
        stoppedReason: "apply cap reached",
      }),
    ]);

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("run-finished")).toBeTruthy());
    expect(screen.getByText(/Postings seen: 10/)).toBeTruthy();
    expect(screen.getByText(/Screenings recorded: 8/)).toBeTruthy();
    expect(screen.getByText(/Blocked: 1/)).toBeTruthy();
    expect(screen.getByText(/Applied: 3\/5/)).toBeTruthy();
    expect(screen.getByText(/Stopped: apply cap reached/)).toBeTruthy();
  });

  it("renders a running run distinctly from a finished one", async () => {
    vi.spyOn(client, "listRuns").mockResolvedValue([
      makeRun({ id: "run-active", status: "running", finishedAt: "" }),
    ]);

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("run-active")).toBeTruthy());
    expect(screen.getByText("Running")).toBeTruthy();
  });

  it("shows a message when no runs are recorded", async () => {
    vi.spyOn(client, "listRuns").mockResolvedValue([]);

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("No runs recorded yet.")).toBeTruthy());
  });
});
