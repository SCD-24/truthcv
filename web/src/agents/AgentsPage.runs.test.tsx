// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RecentRunsSection, STATUS_POLL_IDLE_MS } from "./AgentsPage";
import * as client from "../api/client";
import type { RunPage, RunRecord } from "../api/types";

/** Wrap runs in the paged response shape the endpoint returns. `total`
 * defaults to the page's own length, which is what a single-page history
 * looks like; the pagination tests pass a larger one explicitly. */
function makePage(runs: RunRecord[], total = runs.length, offset = 0): RunPage {
  return { runs, total, limit: 5, offset };
}

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
    queuedForApproval: 2,
    overCapWrites: 0,
    stoppedReason: "",
    note: "",
    discoveryCoverage: [],
    boardBreakdown: [],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("RecentRunsSection", () => {
  it("renders coverage counters and stopped_reason for a finished run", async () => {
    vi.spyOn(client, "listRuns").mockResolvedValue(
      makePage([
        makeRun({
          id: "run-finished",
          status: "completed",
          stoppedReason: "apply cap reached",
        }),
      ]),
    );

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("run-finished")).toBeTruthy());
    expect(screen.getByText(/Postings seen: 10/)).toBeTruthy();
    expect(screen.getByText(/Screenings recorded: 8/)).toBeTruthy();
    expect(screen.getByText(/Blocked: 1/)).toBeTruthy();
    expect(screen.getByText(/Queued for approval: 2/)).toBeTruthy();
    expect(screen.getByText(/Applied: 3\/5/)).toBeTruthy();
    expect(screen.getByText(/Stopped: apply cap reached/)).toBeTruthy();
  });

  it("renders per-channel discovery coverage for a run that recorded it", async () => {
    vi.spyOn(client, "listRuns").mockResolvedValue(
      makePage([
        makeRun({
          id: "run-with-coverage",
          discoveryCoverage: [
            { channel: "feed", board: "LinkedIn", status: "searched", postingsFound: 11, reason: "" },
            { channel: "direct", board: "Ashby", status: "searched", postingsFound: 4, reason: "" },
            { channel: "direct", board: "Greenhouse", status: "searched", postingsFound: 2, reason: "" },
            { channel: "direct", board: "Lever", status: "searched", postingsFound: 0, reason: "" },
            { channel: "direct", board: "Personio", status: "login_walled", postingsFound: 0, reason: "" },
            { channel: "direct", board: "Workday", status: "login_walled", postingsFound: 0, reason: "" },
          ],
        }),
      ]),
    );

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("run-with-coverage")).toBeTruthy());
    expect(
      screen.getByText("Feed: 11 postings · Direct boards: 3 searched, 2 login-walled · Dorks: not reached"),
    ).toBeTruthy();
  });

  it("shows no discovery coverage recorded when a run has none", async () => {
    vi.spyOn(client, "listRuns").mockResolvedValue(
      makePage([makeRun({ id: "run-no-coverage", discoveryCoverage: [] })]),
    );

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("run-no-coverage")).toBeTruthy());
    expect(screen.getByText("Discovery coverage: none recorded")).toBeTruthy();
  });

  it("renders a running run distinctly from a finished one", async () => {
    vi.spyOn(client, "listRuns").mockResolvedValue(
      makePage([makeRun({ id: "run-active", status: "running", finishedAt: "" })]),
    );

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("run-active")).toBeTruthy());
    expect(screen.getByText("Running")).toBeTruthy();
  });

  it("shows a message when no runs are recorded", async () => {
    vi.spyOn(client, "listRuns").mockResolvedValue(makePage([]));

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("No runs recorded yet.")).toBeTruthy());
  });

  it("asks for five runs at a time, newest first", async () => {
    const spy = vi.spyOn(client, "listRuns").mockResolvedValue(makePage([makeRun()]));

    render(<RecentRunsSection />);

    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith(5, 0);
  });

  it("pages forward and back by five, and disables the ends", async () => {
    const spy = vi
      .spyOn(client, "listRuns")
      .mockImplementation(async (_limit?: number, offset = 0) =>
        // A full five-run page, as the endpoint would actually return: a
        // one-row fixture cannot show the label disagreeing with the rows.
        makePage(
          Array.from({ length: 5 }, (_, i) => makeRun({ id: `run-at-${offset + i}` })),
          12,
          offset,
        ),
      );

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("run-at-0")).toBeTruthy());
    // 12 runs, 5 per page -> 3 pages.
    expect(screen.getByText("Page 1 of 3")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByText("run-at-5")).toBeTruthy());
    expect(spy).toHaveBeenCalledWith(5, 5);
    expect(screen.getByText("Page 2 of 3")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByText("run-at-10")).toBeTruthy());
    expect(screen.getByText("Page 3 of 3")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Next" }).hasAttribute("disabled")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() => expect(screen.getByText("Page 2 of 3")).toBeTruthy());
  });

  it("stops at ten pages and says how many runs it is not listing", async () => {
    vi.spyOn(client, "listRuns").mockImplementation(async (_limit?: number, offset = 0) =>
      makePage([makeRun({ id: `run-at-${offset}` })], 63, offset),
    );

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("Page 1 of 10")).toBeTruthy());
    // 63 runs would be 13 pages uncapped. Truncating silently would read as
    // "this is all of them".
    expect(screen.getByText(/13 older runs are not reachable from here/)).toBeTruthy();
    expect(screen.getByText(/Showing the 50 most recent runs/)).toBeTruthy();
  });

  it("does not claim runs are hidden when they all fit", async () => {
    vi.spyOn(client, "listRuns").mockResolvedValue(makePage([makeRun()], 4));

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("Page 1 of 1")).toBeTruthy());
    expect(screen.queryByText(/not listed here/)).toBeNull();
  });

  it("clicking a run row opens a dialog with the board breakdown table", async () => {
    vi.spyOn(client, "listRuns").mockResolvedValue(
      makePage([
        makeRun({
          id: "run-with-breakdown",
          boardBreakdown: [
            { board: "linkedin", postingsSeen: 2, forReview: 0, rejected: 1 },
            { board: "lever", postingsSeen: 1, forReview: 1, rejected: 0 },
          ],
        }),
      ]),
    );

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("run-with-breakdown")).toBeTruthy());
    const runRow = screen.getByRole("button", { name: /run-with-breakdown/ });
    fireEvent.click(runRow);

    await waitFor(() => {
      expect(screen.getByText(/Job board/)).toBeTruthy();
      expect(screen.getByText("linkedin")).toBeTruthy();
      expect(screen.getByText("lever")).toBeTruthy();
    });
  });

  it("pressing Enter on a focused run row opens the modal", async () => {
    vi.spyOn(client, "listRuns").mockResolvedValue(
      makePage([makeRun({ id: "run-keyboard", boardBreakdown: [] })]),
    );

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("run-keyboard")).toBeTruthy());
    const runRow = screen.getByRole("button", { name: /run-keyboard/ });
    runRow.focus();
    fireEvent.keyDown(runRow, { key: "Enter" });

    await waitFor(() => {
      expect(screen.getByText(/Run run-keyboard/)).toBeTruthy();
    });
  });

  it("closing the modal hides it", async () => {
    vi.spyOn(client, "listRuns").mockResolvedValue(
      makePage([makeRun({ id: "run-closeable", boardBreakdown: [] })]),
    );

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("run-closeable")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /run-closeable/ }));

    await waitFor(() => {
      expect(screen.getByText(/Run run-closeable/)).toBeTruthy();
    });

    const closeButton = screen.getByRole("button", { name: "Close" });
    fireEvent.click(closeButton);

    await waitFor(() => {
      expect(screen.queryByText(/Run run-closeable/)).toBeNull();
    });
  });

  it("steps back when the page it is on stops existing", async () => {
    // A run history that shrinks under the current page — the last page is
    // otherwise left empty with Previous as the only way out. The shrink is
    // noticed by the section's own poll, so drive that clock rather than
    // waiting ten real seconds for it.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let total = 12;
    vi.spyOn(client, "listRuns").mockImplementation(async (_limit?: number, offset = 0) =>
      makePage(offset < total ? [makeRun({ id: `run-at-${offset}` })] : [], total, offset),
    );

    try {
      render(<RecentRunsSection />);
      await waitFor(() => expect(screen.getByText("Page 1 of 3")).toBeTruthy());
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
      await waitFor(() => expect(screen.getByText("Page 3 of 3")).toBeTruthy());

      total = 6;
      await vi.advanceTimersByTimeAsync(STATUS_POLL_IDLE_MS + 1);
      await waitFor(() => expect(screen.getByText("Page 2 of 2")).toBeTruthy());
    } finally {
      vi.useRealTimers();
    }
  });

  it("never labels a page it is not showing, even when the fetch fails", async () => {
    // `page` flips on click; the rows only change when the response lands. If
    // the label follows the click, a failed page-2 fetch leaves "Page 2" over
    // page 1's runs — and a run's counters read under the wrong page number
    // are a false statement about which runs they describe.
    vi.spyOn(client, "listRuns").mockImplementation(async (_limit?: number, offset = 0) => {
      if (offset > 0) throw new Error("network down");
      return makePage([makeRun({ id: "page-one-run" })], 12, 0);
    });

    render(<RecentRunsSection />);
    await waitFor(() => expect(screen.getByText("page-one-run")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(screen.getByText(/network down/)).toBeTruthy());
    expect(screen.getByText("page-one-run")).toBeTruthy();
    expect(screen.getByText("Page 1 of 3")).toBeTruthy();
  });

  it("says the page is empty, not that no runs exist, when history has runs", async () => {
    vi.spyOn(client, "listRuns").mockResolvedValue(makePage([], 12, 5));

    render(<RecentRunsSection />);

    await waitFor(() => expect(screen.getByText("No runs on this page.")).toBeTruthy());
    // And there is a way back off it.
    expect(screen.getByRole("button", { name: "Previous" })).toBeTruthy();
  });
});
