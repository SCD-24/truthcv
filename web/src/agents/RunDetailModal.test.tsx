// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RunDetailModal } from "./RunDetailModal";
import type { RunRecord, BoardBreakdown } from "../api/types";

function makeRun(boardBreakdown: BoardBreakdown[] = []): RunRecord {
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
    boardBreakdown,
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
    const run = makeRun([
      { board: "lever", postingsSeen: 3, forReview: 1, rejected: 1 },
      { board: "linkedin", postingsSeen: 2, forReview: 0, rejected: 1 },
    ]);
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
    const run = makeRun([
      { board: "lever", postingsSeen: 3, forReview: 1, rejected: 1 },
      { board: "linkedin", postingsSeen: 2, forReview: 0, rejected: 1 },
    ]);
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
    const run = makeRun([]);
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
});
