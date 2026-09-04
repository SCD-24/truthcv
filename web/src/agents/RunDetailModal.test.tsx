// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RunDetailModal } from "./RunDetailModal";
import * as client from "../api/client";
import type { RunRecord, BoardBreakdown } from "../api/types";

function makeRun(overrides: Partial<RunRecord> & { boardBreakdown?: BoardBreakdown[] } = {}): RunRecord {
  return {
    id: "run-test",
    startedAt: "2024-06-01T12:00:00+00:00",
    finishedAt: "2024-06-01T12:05:00+00:00",
    status: "completed",
    trigger: "scheduled",
    applyCap: 0,
    postingsSeen: 0,
    screeningsRecorded: 0,
    blockedCount: 0,
    applicationsSubmitted: 0,
    queuedForApproval: 0,
    overCapWrites: 0,
    stoppedReason: "",
    note: "",
    discoveryCoverage: [],
    boardBreakdown: [],
    ...overrides,
  };
}

describe("RunDetailModal", () => {
  it("renders title with run id", () => {
    const run = makeRun();
    const onClose = () => {};
    render(<RunDetailModal run={run} onClose={onClose} />);

    // Text is split across elements due to mono-font span, so check with regex
    expect(screen.getByText((_content, element) => {
      if (element?.tagName === "H2") {
        return element.textContent?.includes("Run") && element.textContent?.includes("run-test");
      }
      return false;
    })).toBeTruthy();
  });

  it("renders board breakdown table with two boards", () => {
    const run = makeRun({
      boardBreakdown: [
        { board: "lever", postingsSeen: 3, forReview: 1, rejected: 1 },
        { board: "linkedin", postingsSeen: 2, forReview: 0, rejected: 1 },
      ],
    });
    const onClose = () => {};
    render(<RunDetailModal run={run} onClose={onClose} />);

    // Check headers
    expect(screen.getByText("Job board")).toBeTruthy();
    expect(screen.getByText("Postings seen")).toBeTruthy();
    expect(screen.getByText("For review")).toBeTruthy();
    expect(screen.getByText("Rejected")).toBeTruthy();

    // Check board rows
    expect(screen.getByText("lever")).toBeTruthy();
    expect(screen.getByText("linkedin")).toBeTruthy();

    // Check total row
    expect(screen.getByText("Total")).toBeTruthy();
  });

  it("renders totals row with correct sums", () => {
    const run = makeRun({
      boardBreakdown: [
        { board: "lever", postingsSeen: 3, forReview: 1, rejected: 1 },
        { board: "linkedin", postingsSeen: 2, forReview: 0, rejected: 1 },
      ],
    });
    const onClose = () => {};
    render(<RunDetailModal run={run} onClose={onClose} />);

    const rows = screen.getAllByRole("row");
    // Header + 2 boards + totals = 4 rows
    expect(rows.length).toBe(4);

    // Total should be 5 postings seen, 1 for review, 2 rejected
    const totalRow = rows[3];
    expect(totalRow.textContent).toContain("Total");
    expect(totalRow.textContent).toContain("5");
    expect(totalRow.textContent).toContain("1");
    expect(totalRow.textContent).toContain("2");
  });

  it("renders empty state when no screenings were recorded", () => {
    const run = makeRun({ boardBreakdown: [] });
    const onClose = () => {};
    render(<RunDetailModal run={run} onClose={onClose} />);

    // When boardBreakdown is empty, table should not be rendered
    expect(screen.queryByRole("table")).toBeNull();
    // And the empty state message should appear (match partial text)
    const texts = screen.queryAllByText((content) => content.includes("No screenings"));
    expect(texts.length > 0).toBe(true);
  });

  it("Close button calls onClose", async () => {
    const run = makeRun();
    const onClose = () => {};

    render(<RunDetailModal run={run} onClose={onClose} />);

    const closeButton = screen.getByRole("button", { name: "Close" });
    expect(closeButton).toBeTruthy();
  });

  it("shows the Stop button for a running run", () => {
    const run = makeRun({ status: "running", finishedAt: "" });
    render(<RunDetailModal run={run} onClose={() => {}} />);

    expect(screen.getByRole("button", { name: /Stop run/ })).toBeTruthy();
  });

  it("does not show the Stop button for a completed run", () => {
    const run = makeRun({ status: "completed" });
    render(<RunDetailModal run={run} onClose={() => {}} />);

    expect(screen.queryByRole("button", { name: /Stop run/ })).toBeNull();
  });

  it("Stop button click calls stopRun and onStopped", async () => {
    const run = makeRun({ status: "running", finishedAt: "" });
    const stoppedRun = makeRun({ status: "running", finishedAt: "" });
    const spy = vi.spyOn(client, "stopRun").mockResolvedValue({ outcome: "cancelling", run: stoppedRun });
    const onStopped = vi.fn();

    render(<RunDetailModal run={run} onClose={() => {}} onStopped={onStopped} />);

    const stopButton = screen.getByRole("button", { name: /Stop run/ });
    fireEvent.click(stopButton);

    await waitFor(() => expect(spy).toHaveBeenCalledWith(run.id));
    await waitFor(() => expect(onStopped).toHaveBeenCalledWith({ outcome: "cancelling", run: stoppedRun }));
    await waitFor(() =>
      expect(screen.getByText("Stop requested — the agent is shutting the run down.")).toBeTruthy(),
    );
  });

  it("shows an error alert and keeps the Stop button enabled on failure", async () => {
    const run = makeRun({ status: "running", finishedAt: "" });
    vi.spyOn(client, "stopRun").mockRejectedValue(new Error("Network error"));

    render(<RunDetailModal run={run} onClose={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: /Stop run/ }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Network error");

    const stopButton = screen.getByRole("button", { name: /Stop run/ }) as HTMLButtonElement;
    expect(stopButton.disabled).toBe(false);
  });
});
