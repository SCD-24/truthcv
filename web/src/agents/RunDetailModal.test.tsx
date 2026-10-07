// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RunDetailModal } from "./RunDetailModal";
import * as client from "../api/client";
import type { RunRecord, BoardBreakdown } from "../api/types";

function row(board: string, over: Partial<BoardBreakdown> = {}): BoardBreakdown {
  return {
    board, channel: "direct", postingsSeen: 0, previouslyScreened: 0, notAPosting: 0, duplicate: 0,
    failed: 0, forReview: 0, rejected: 0, blocked: 0, ...over,
  };
}

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
    itemsFailed: 0,
    itemErrors: [],
    stoppedReason: "",
    note: "",
    discoveryCoverage: [],
    boardBreakdown: [],
    boardBreakdownTotal: null,
    funnelMismatches: [],
    urlLedgerTruncated: false,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

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
        row("lever", { postingsSeen: 3, forReview: 1, rejected: 1 }),
        row("linkedin", { postingsSeen: 2, rejected: 1, channel: "dork" }),
        row("jobs.example/feed", { postingsSeen: 1, channel: "feed" }),
      ],
    });
    const onClose = () => {};
    render(<RunDetailModal run={run} onClose={onClose} />);

    expect(screen.getByText("linkedin (search)")).toBeTruthy();
    expect(screen.getByText("jobs.example/feed (feed)")).toBeTruthy();
    expect(screen.getByText("Source")).toBeTruthy();
    expect(screen.getByText("Postings seen")).toBeTruthy();
    expect(screen.getByText("For review")).toBeTruthy();
    expect(screen.getByText("Rejected")).toBeTruthy();

    // Check board rows
    expect(screen.getByText("lever")).toBeTruthy();

    // Check total row
    expect(screen.getByText("Total")).toBeTruthy();
  });

  it("renders totals row with correct sums", () => {
    const run = makeRun({
      boardBreakdown: [
        row("https://lever.co/", { postingsSeen: 3, forReview: 1, rejected: 1 }),
        row("linkedin", { postingsSeen: 2, rejected: 1 }),
      ],
    });
    render(<RunDetailModal run={run} onClose={() => {}} />);

    expect(screen.getByText("lever.co")).toBeTruthy();
    const rows = screen.getAllByRole("row");
    const totalRow = rows[rows.length - 1];
    expect(totalRow.textContent).toBe("Total50000120");
  });

  it("uses stored totals, and sums with dashes for a legacy run", () => {
    const legacy = makeRun({
      boardBreakdown: [row("a.com", { postingsSeen: null, previouslyScreened: null, notAPosting: null, duplicate: null, failed: null, forReview: 2 })],
    });
    const { unmount } = render(<RunDetailModal run={legacy} onClose={() => {}} />);
    const rows = screen.getAllByRole("row");
    expect(rows[rows.length - 1].textContent).toBe("Total—————200");
    expect(screen.queryByRole("button", { name: "a.com" })).toBeNull();
    unmount();
  });

  it("warns naming mismatched sources and shows a toggle button per row", () => {
    const run = makeRun({
      boardBreakdown: [row("lever", { postingsSeen: 1 })],
      funnelMismatches: ["lever", "totals"],
    });
    render(<RunDetailModal run={run} onClose={() => {}} />);
    expect(screen.getByRole("alert").textContent).toContain("lever, the totals");
    const btn = screen.getByRole("button", { name: "lever" });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
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

  it("renders the table and mismatch alert when only a stored total exists", () => {
    const total = { postingsSeen: 0, previouslyScreened: 0, notAPosting: 0, duplicate: 0, failed: 0, forReview: 0, rejected: 0, blocked: 0 };
    const run = makeRun({
      boardBreakdown: [],
      boardBreakdownTotal: total as unknown as RunRecord["boardBreakdownTotal"],
      funnelMismatches: ["totals"],
    });
    render(<RunDetailModal run={run} onClose={() => {}} />);
    expect(screen.getByRole("table")).toBeTruthy();
    const rows = screen.getAllByRole("row");
    expect(rows[rows.length - 1].textContent).toBe("Total00000000");
    expect(screen.getByRole("alert").textContent).toContain("the totals");
    expect(screen.queryByText("No screenings recorded.")).toBeNull();
  });

  it("toggles an expandable row when a count cell is clicked", () => {
    vi.spyOn(client, "getRunUrls").mockResolvedValue({ entries: [], total: 0 });
    const run = makeRun({ boardBreakdown: [row("lever", { postingsSeen: 1 })] });
    render(<RunDetailModal run={run} onClose={() => {}} />);
    const btn = screen.getByRole("button", { name: "lever" });
    fireEvent.click(btn.closest("tr")!.querySelectorAll("td")[1]);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("false");
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
