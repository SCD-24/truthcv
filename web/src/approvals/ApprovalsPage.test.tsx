// @vitest-environment jsdom
/** Approvals page: the operator's queue. Stubbing follows ScreeningsPage.test.tsx. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  bulkDeleteScreenings,
  bulkSetApproval,
  deleteScreening,
  generateScreeningLetter,
  getScreeningLetter,
  listAppliedScreenings,
  markScreeningApplied,
  listApprovedApplications,
  listDidNotPass,
  listPendingApprovals,
  listRejectedApprovals,
  saveScreeningLetter,
  setScreeningApproval,
  setScreeningPostingText,
  setScreeningUrl,
} from "../api/client";
import type { ScreeningRecord } from "../api/types";
import { ApprovalsPage, byDateDesc, orderingDate } from "./ApprovalsPage";

vi.mock("../api/client", () => ({
  listPendingApprovals: vi.fn(),
  listApprovedApplications: vi.fn(),
  listRejectedApprovals: vi.fn(),
  listDidNotPass: vi.fn(),
  listAppliedScreenings: vi.fn(),
  setScreeningApproval: vi.fn(),
  bulkSetApproval: vi.fn(),
  deleteScreening: vi.fn(),
  bulkDeleteScreenings: vi.fn(),
  setScreeningUrl: vi.fn(),
  setScreeningPostingText: vi.fn(),
  getScreeningLetter: vi.fn(),
  generateScreeningLetter: vi.fn(),
  markScreeningApplied: vi.fn(),
  saveScreeningLetter: vi.fn(),
}));

afterEach(() => {
  cleanup();
  // Without this, spy call counts leak between tests and a later
  // `not.toHaveBeenCalled()` sees an earlier test's call.
  vi.clearAllMocks();
});

// The list endpoint never carries drafts (PendingCard fetches its own), so
// every test needs a stub; the no-draft case is the common one, and the
// cover-letter tests below override it before rendering.
beforeEach(() => {
  vi.mocked(getScreeningLetter).mockResolvedValue(null);
  vi.mocked(listRejectedApprovals).mockResolvedValue([]);
  vi.mocked(listDidNotPass).mockResolvedValue([]);
  vi.mocked(listAppliedScreenings).mockResolvedValue([]);
});

function makeRecord(overrides: Partial<ScreeningRecord> = {}): ScreeningRecord {
  return {
    id: "s1",
    company: "Grafana Labs",
    role: "Staff AI Engineer",
    url: "https://grafana.com/jobs/1",
    screenedDate: "2026-08-23",
    verdict: "deferred",
    failingCriterion: "entity",
    reason: "German hiring entity unverified",
    cooldownExpires: "",
    source: "agent",
    postingText: "Staff AI Engineer, Germany (Remote).",
    postedDate: "2026-08-20",
    approval: "pending",
    applyAttempts: 0,
    applyError: "",
    createdAt: "2026-08-23T19:00:00Z",
    updatedAt: "2026-08-23T19:00:00Z",
    ...overrides,
  };
}

async function renderPage(
  pending: ScreeningRecord[],
  approved: ScreeningRecord[] = [],
  lists: {
    rejected?: ScreeningRecord[];
    didNotPass?: ScreeningRecord[];
    applied?: ScreeningRecord[];
  } = {},
) {
  vi.mocked(listPendingApprovals).mockResolvedValue(pending);
  vi.mocked(listApprovedApplications).mockResolvedValue(approved);
  if (lists.rejected) vi.mocked(listRejectedApprovals).mockResolvedValue(lists.rejected);
  if (lists.didNotPass) vi.mocked(listDidNotPass).mockResolvedValue(lists.didNotPass);
  if (lists.applied) vi.mocked(listAppliedScreenings).mockResolvedValue(lists.applied);
  render(<ApprovalsPage onBack={() => {}} />);
  await waitFor(() => expect(listPendingApprovals).toHaveBeenCalled());
}

/** Tabs lazy-mount their panels, so anything not on the default Found tab
 * must be revealed by clicking its tab first. */
function clickTab(name: string | RegExp) {
  fireEvent.click(screen.getByRole("tab", { name }));
}

describe("ApprovalsPage", () => {
  it("renders four tabs with the counts of each queue", async () => {
    await renderPage(
      [makeRecord(), makeRecord({ id: "s2", company: "n8n" })],
      [makeRecord({ id: "a1", approval: "approved" })],
      {
        rejected: [makeRecord({ id: "r1", approval: "rejected" })],
        didNotPass: [makeRecord({ id: "d1", verdict: "rejected", approval: "" })],
        applied: [
          makeRecord({ id: "ap1", approval: "applied" }),
          makeRecord({ id: "ap2", approval: "applied" }),
        ],
      },
    );
    expect(await screen.findByRole("tab", { name: "Found (2)" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Queued (1)" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Rejected (2)" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Applied (2)" })).toBeTruthy();
  });

  it("renders a pending item with the agent's deferral reason", async () => {
    await renderPage([makeRecord()]);
    expect(await screen.findByText("Grafana Labs")).toBeTruthy();
    expect(screen.getByText(/German hiring entity unverified/)).toBeTruthy();
  });

  it("shows the empty state when nothing is waiting", async () => {
    await renderPage([]);
    expect(await screen.findByText(/nothing waiting/i)).toBeTruthy();
  });

  it("each tab renders its own empty state", async () => {
    await renderPage([makeRecord()]);
    clickTab(/queued/i);
    expect(await screen.findByText(/nothing queued/i)).toBeTruthy();
    clickTab(/rejected/i);
    expect(screen.getByText(/nothing rejected/i)).toBeTruthy();
    clickTab(/applied/i);
    expect(screen.getByText(/nothing applied/i)).toBeTruthy();
    clickTab(/found/i);
    expect(screen.getByText("Grafana Labs")).toBeTruthy();
  });

  it("approving calls through and removes the row", async () => {
    // Approve is disabled until a draft exists (Task 10), so this needs one stubbed.
    vi.mocked(getScreeningLetter).mockResolvedValue({
      text: "Dear hiring team,",
      paragraphs: [],
      source: "generated",
      updatedAt: "2026-08-24T10:00:00Z",
    });
    vi.mocked(setScreeningApproval).mockResolvedValue(makeRecord({ approval: "approved" }));
    await renderPage([makeRecord()]);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^approve$/i }).hasAttribute("disabled")).toBe(
        false,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    await waitFor(() => expect(setScreeningApproval).toHaveBeenCalledWith("s1", "approved"));
  });

  it("rejecting calls through", async () => {
    vi.mocked(setScreeningApproval).mockResolvedValue(makeRecord({ approval: "rejected" }));
    await renderPage([makeRecord()]);
    fireEvent.click(await screen.findByRole("button", { name: /^reject$/i }));
    await waitFor(() => expect(setScreeningApproval).toHaveBeenCalledWith("s1", "rejected"));
  });

  it("bulk approve sends every selected id", async () => {
    vi.mocked(bulkSetApproval).mockResolvedValue({ results: [] });
    await renderPage([makeRecord(), makeRecord({ id: "s2", company: "n8n" })]);
    fireEvent.click(await screen.findByRole("checkbox", { name: /select all/i }));
    fireEvent.click(screen.getByRole("button", { name: /approve selected/i }));
    await waitFor(() =>
      expect(bulkSetApproval).toHaveBeenCalledWith(["s1", "s2"], "approved"),
    );
  });

  it("shows attempt count and last error for a failing approved item", async () => {
    await renderPage(
      [],
      [makeRecord({ approval: "approved", applyAttempts: 3, applyError: "form 404" })],
    );
    clickTab(/queued/i);
    expect(await screen.findByText(/form 404/)).toBeTruthy();
    expect(screen.getByText(/3 attempts/i)).toBeTruthy();
  });

  it("renders a URL entry field for a pending record with no url", async () => {
    await renderPage([makeRecord({ url: "" })]);
    expect(await screen.findByLabelText(/posting url/i)).toBeTruthy();
  });

  it("does not render a URL entry field for a record that already has a url", async () => {
    await renderPage([makeRecord()]);
    await screen.findByText("Grafana Labs");
    expect(screen.queryByLabelText(/posting url/i)).toBeNull();
  });

  it("editing an existing url on a queued record prefills the field and saves the new value", async () => {
    vi.mocked(setScreeningUrl).mockResolvedValue(
      makeRecord({
        id: "a1",
        approval: "approved",
        url: "https://x.example/updated",
      }),
    );
    await renderPage([], [makeRecord({ id: "a1", approval: "approved" })]);
    clickTab(/queued/i);
    fireEvent.click(await screen.findByRole("button", { name: /edit url/i }));
    const field = screen.getByLabelText(/posting url/i) as HTMLInputElement;
    expect(field.value).toBe("https://grafana.com/jobs/1");
    fireEvent.change(field, { target: { value: "https://x.example/updated" } });
    fireEvent.click(screen.getByRole("button", { name: /save url/i }));
    await waitFor(() =>
      expect(setScreeningUrl).toHaveBeenCalledWith("a1", "https://x.example/updated"),
    );
    expect(await screen.findByText("https://x.example/updated")).toBeTruthy();
  });

  it("cancelling an edit discards the draft and restores the original link", async () => {
    await renderPage([], [makeRecord({ id: "a1", approval: "approved" })]);
    vi.mocked(setScreeningUrl).mockClear();
    clickTab(/queued/i);
    fireEvent.click(await screen.findByRole("button", { name: /edit url/i }));
    fireEvent.change(screen.getByLabelText(/posting url/i), {
      target: { value: "https://discard.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(screen.queryByLabelText(/posting url/i)).toBeNull();
    expect(await screen.findByText("https://grafana.com/jobs/1")).toBeTruthy();
    expect(setScreeningUrl).not.toHaveBeenCalled();
  });

  it("a rejected record renders its url and can be edited", async () => {
    vi.mocked(setScreeningUrl).mockResolvedValue(
      makeRecord({ id: "r1", approval: "rejected", url: "https://x.example/rejected" }),
    );
    await renderPage([], [], {
      rejected: [makeRecord({ id: "r1", company: "Pleo", approval: "rejected" })],
    });
    clickTab(/rejected/i);
    expect(await screen.findByText("https://grafana.com/jobs/1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /edit url/i }));
    fireEvent.change(screen.getByLabelText(/posting url/i), {
      target: { value: "https://x.example/rejected" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save url/i }));
    await waitFor(() =>
      expect(setScreeningUrl).toHaveBeenCalledWith("r1", "https://x.example/rejected"),
    );
    expect(await screen.findByText("https://x.example/rejected")).toBeTruthy();
  });

  it("saving a url calls through and renders the link in place of the field", async () => {
    vi.mocked(setScreeningUrl).mockResolvedValue(
      makeRecord({ url: "https://x.example/job" }),
    );
    await renderPage([makeRecord({ url: "" })]);
    fireEvent.change(await screen.findByLabelText(/posting url/i), {
      target: { value: "https://x.example/job" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save url/i }));
    await waitFor(() =>
      expect(setScreeningUrl).toHaveBeenCalledWith("s1", "https://x.example/job"),
    );
    expect(await screen.findByText("https://x.example/job")).toBeTruthy();
    expect(screen.queryByLabelText(/posting url/i)).toBeNull();
  });

  it("shows a warning and URL field for an approved record with no url", async () => {
    await renderPage([], [makeRecord({ approval: "approved", url: "" })]);
    clickTab(/queued/i);
    expect(await screen.findByLabelText(/posting url/i)).toBeTruthy();
    expect(screen.getByText(/cannot be applied to on the next run/i)).toBeTruthy();
  });
});

describe("ApprovalsPage cover letter", () => {
  it("offers Generate when there is no draft, and blocks Approve until there is one", async () => {
    vi.mocked(getScreeningLetter).mockResolvedValue(null);
    await renderPage([makeRecord()]);
    expect(await screen.findByRole("button", { name: /Generate cover letter/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Reject" }).hasAttribute("disabled")).toBe(false);
  });

  it("generating shows the text and unblocks Approve", async () => {
    vi.mocked(getScreeningLetter).mockResolvedValue(null);
    vi.mocked(generateScreeningLetter).mockResolvedValue({
      text: "Dear hiring team,",
      paragraphs: [],
      source: "generated",
      updatedAt: "2026-08-24T10:00:00Z",
    });
    await renderPage([makeRecord()]);
    fireEvent.click(await screen.findByRole("button", { name: /Generate cover letter/ }));
    await waitFor(() => expect(generateScreeningLetter).toHaveBeenCalledWith("s1"));
    expect(await screen.findByDisplayValue("Dear hiring team,")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Approve" }).hasAttribute("disabled")).toBe(false),
    );
  });

  it("saving an edit sends the text verbatim and marks it as yours", async () => {
    vi.mocked(getScreeningLetter).mockResolvedValue({
      text: "Dear hiring team,",
      paragraphs: [],
      source: "generated",
      updatedAt: "2026-08-24T10:00:00Z",
    });
    vi.mocked(saveScreeningLetter).mockResolvedValue({
      text: "My own words.",
      paragraphs: [],
      source: "operator",
      updatedAt: "2026-08-24T10:05:00Z",
    });
    await renderPage([makeRecord()]);
    const field = await screen.findByDisplayValue("Dear hiring team,");
    fireEvent.change(field, { target: { value: "My own words." } });
    fireEvent.click(screen.getByRole("button", { name: "Save letter" }));
    await waitFor(() => expect(saveScreeningLetter).toHaveBeenCalledWith("s1", "My own words."));
    expect(await screen.findByText(/not checked/)).toBeTruthy();
  });

  // The mock here rejects with an already-composed Error — the mock stands in for
  // whatever message errorDetailToMessage would have produced, it doesn't
  // go through errorDetailToMessage. So this only proves the page renders
  // an error it's handed verbatim, not that the guardrail-block message is
  // composed correctly; that composition is pinned in errorDetail.test.ts
  // ("object detail (guardrail block)"), which exercises errorDetailToMessage
  // directly and unmocked.
  it("renders the generation error message verbatim in the alert", async () => {
    vi.mocked(getScreeningLetter).mockResolvedValue(null);
    vi.mocked(generateScreeningLetter).mockRejectedValue(
      new Error(
        "The letter was blocked by the truthfulness guardrail. Blocked: Led a team of 50 engineers.",
      ),
    );
    await renderPage([makeRecord()]);
    fireEvent.click(await screen.findByRole("button", { name: /Generate cover letter/ }));
    expect(await screen.findByText(/Led a team of 50 engineers\./)).toBeTruthy();
  });

  it("says why Generate is unavailable when no posting text was captured", async () => {
    vi.mocked(getScreeningLetter).mockResolvedValue(null);
    await renderPage([makeRecord({ postingText: "" })]);
    const button = await screen.findByRole("button", { name: /Generate cover letter/ });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/No posting text/)).toBeTruthy();
    expect(screen.getByLabelText(/posting text/i)).toBeTruthy();
  });

  it("pasting and saving posting text enables Generate cover letter", async () => {
    vi.mocked(getScreeningLetter).mockResolvedValue(null);
    vi.mocked(setScreeningPostingText).mockResolvedValue(
      makeRecord({ postingText: "Some pasted posting text." }),
    );
    await renderPage([makeRecord({ postingText: "" })]);
    const field = await screen.findByLabelText(/posting text/i);
    fireEvent.change(field, { target: { value: "Some pasted posting text." } });
    fireEvent.click(screen.getByRole("button", { name: /save posting text/i }));
    await waitFor(() =>
      expect(setScreeningPostingText).toHaveBeenCalledWith("s1", "Some pasted posting text."),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Generate cover letter/ }).hasAttribute("disabled"),
      ).toBe(false),
    );
    expect(screen.getByRole("button", { name: "Approve" }).hasAttribute("disabled")).toBe(true);
  });

  it("shows the posted and found dates", async () => {
    vi.mocked(getScreeningLetter).mockResolvedValue(null);
    await renderPage([makeRecord()]);
    expect(await screen.findByText(/Posted 2026-08-20/)).toBeTruthy();
    expect(screen.getByText(/Found 2026-08-23/)).toBeTruthy();
  });
});

describe("ApprovalsPage reviewable lists", () => {
  it("the Rejected tab lists agent-rejected and user-rejected records with distinct labels", async () => {
    await renderPage([], [], {
      didNotPass: [
        makeRecord({ id: "d1", company: "SumUp", verdict: "rejected", approval: "", failingCriterion: "remote" }),
      ],
      rejected: [
        makeRecord({ id: "r1", company: "Pleo", approval: "rejected" }),
      ],
    });
    clickTab(/rejected \(2\)/i);
    expect(await screen.findByText("SumUp")).toBeTruthy();
    expect(screen.getByText("Pleo")).toBeTruthy();
    expect(screen.getByText("Rejected by agent")).toBeTruthy();
    expect(screen.getByText("Rejected by you")).toBeTruthy();
  });

  it("moving one back queues it and takes it out of the Rejected tab", async () => {
    vi.mocked(setScreeningApproval).mockResolvedValue(
      makeRecord({ id: "r1", company: "Pleo", approval: "pending" }),
    );
    await renderPage([], [], {
      rejected: [makeRecord({ id: "r1", company: "Pleo", approval: "rejected" })],
    });
    clickTab(/rejected/i);
    fireEvent.click(await screen.findByRole("button", { name: "Move to approvals" }));
    await waitFor(() => expect(setScreeningApproval).toHaveBeenCalledWith("r1", "pending"));
    await waitFor(() =>
      expect(screen.queryAllByRole("button", { name: "Move to approvals" }).length).toBe(0),
    );
    // The row joined the Found queue without a refetch.
    clickTab(/found/i);
    expect(await screen.findByText("Pleo")).toBeTruthy();
  });

  it("moving a queued record back to Found unqueues it and updates both tab counts", async () => {
    vi.mocked(setScreeningApproval).mockResolvedValue(
      makeRecord({ id: "s1", approval: "pending" }),
    );
    await renderPage([], [makeRecord({ id: "s1", approval: "approved" })]);
    expect(await screen.findByRole("tab", { name: "Found (0)" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Queued (1)" })).toBeTruthy();
    clickTab(/queued/i);
    fireEvent.click(await screen.findByRole("button", { name: /move back to found/i }));
    await waitFor(() => expect(setScreeningApproval).toHaveBeenCalledWith("s1", "pending"));
    await waitFor(() =>
      expect(screen.queryAllByRole("button", { name: /move back to found/i }).length).toBe(0),
    );
    expect(await screen.findByRole("tab", { name: "Found (1)" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Queued (0)" })).toBeTruthy();
    clickTab(/found/i);
    expect(await screen.findByText("Grafana Labs")).toBeTruthy();
  });
});

describe("ApprovalsPage applied tab", () => {
  it("lists applied records read-only, with no action buttons", async () => {
    await renderPage([], [], {
      applied: [
        makeRecord({ id: "ap1", company: "Wolt", approval: "applied" }),
        makeRecord({ id: "ap2", company: "Spotify", approval: "applied", url: "" }),
      ],
    });
    clickTab(/applied/i);
    // AppliedRow prints "company — role" in one node, so match on a substring.
    expect(await screen.findByText(/Wolt/)).toBeTruthy();
    expect(screen.getByText(/Spotify/)).toBeTruthy();
    expect(screen.getByText(/applications page/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^approve$/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^reject$/i })).toBeNull();
    expect(screen.queryAllByRole("button", { name: "Move to approvals" }).length).toBe(0);
    expect(screen.queryByRole("button", { name: /save url/i })).toBeNull();
  });
});

describe("ApprovalsPage rejected tab delete", () => {
  it("deletes one rejected row after confirming", async () => {
    vi.mocked(deleteScreening).mockResolvedValue(undefined);
    await renderPage([], [], {
      rejected: [makeRecord({ id: "r1", company: "Pleo", approval: "rejected" })],
    });
    clickTab(/rejected/i);
    fireEvent.click(
      await screen.findByRole("button", { name: "Delete rejected posting for Pleo" }),
    );
    expect(deleteScreening).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteScreening).toHaveBeenCalledWith("r1"));
    await waitFor(() => expect(screen.queryByText("Pleo")).toBeNull());
  });

  it("requires confirming the dialog before any delete request fires", async () => {
    await renderPage([], [], {
      rejected: [makeRecord({ id: "r1", company: "Pleo", approval: "rejected" })],
    });
    clickTab(/rejected/i);
    fireEvent.click(
      await screen.findByRole("button", { name: "Delete rejected posting for Pleo" }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(deleteScreening).not.toHaveBeenCalled();
    expect(bulkDeleteScreenings).not.toHaveBeenCalled();
    expect(screen.getByText("Pleo")).toBeTruthy();
  });

  it("select-all then Delete selected calls bulk delete for every rejected row", async () => {
    vi.mocked(bulkDeleteScreenings).mockResolvedValue({
      results: [
        { id: "r1", ok: true },
        { id: "r2", ok: true },
      ],
    });
    await renderPage([], [], {
      rejected: [
        makeRecord({ id: "r1", company: "Pleo", approval: "rejected" }),
        makeRecord({ id: "r2", company: "SumUp", approval: "rejected" }),
      ],
    });
    clickTab(/rejected/i);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select all rejected" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete selected" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(bulkDeleteScreenings).toHaveBeenCalledWith(expect.arrayContaining(["r1", "r2"])),
    );
    await waitFor(() => expect(screen.queryByText("Pleo")).toBeNull());
    expect(screen.queryByText("SumUp")).toBeNull();
  });

  it("a partial bulk-delete failure leaves the failed row visible with an error message", async () => {
    vi.mocked(bulkDeleteScreenings).mockResolvedValue({
      results: [
        { id: "r1", ok: true },
        { id: "r2", ok: false },
      ],
    });
    await renderPage([], [], {
      rejected: [
        makeRecord({ id: "r1", company: "Pleo", approval: "rejected" }),
        makeRecord({ id: "r2", company: "SumUp", approval: "rejected" }),
      ],
    });
    clickTab(/rejected/i);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select all rejected" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete selected" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByText("Pleo")).toBeNull());
    expect(await screen.findByText("SumUp")).toBeTruthy();
    expect(await screen.findByText("1 could not be deleted.")).toBeTruthy();
  });

  it("selecting rows on the Rejected tab does not change the Found tab's selection", async () => {
    await renderPage([makeRecord({ id: "s1", company: "Found Co" })], [], {
      rejected: [makeRecord({ id: "r1", company: "Rejected Co", approval: "rejected" })],
    });
    // Plain `.checked` rather than jest-dom's toBeChecked: this project does
    // not install @testing-library/jest-dom, so that matcher is undefined.
    const foundCheckbox = (await screen.findByRole("checkbox", {
      name: "Select Found Co",
    })) as HTMLInputElement;
    fireEvent.click(foundCheckbox);
    expect(foundCheckbox.checked).toBe(true);

    clickTab(/rejected/i);
    const rejectedCheckbox = (await screen.findByRole("checkbox", {
      name: "Select Rejected Co",
    })) as HTMLInputElement;
    fireEvent.click(rejectedCheckbox);
    expect(rejectedCheckbox.checked).toBe(true);

    clickTab(/found/i);
    const foundCheckboxAgain = (await screen.findByRole("checkbox", {
      name: "Select Found Co",
    })) as HTMLInputElement;
    expect(foundCheckboxAgain.checked).toBe(true);
  });
});

describe("Found ordering", () => {
  it("orders by the posting's own date, newest first", () => {
    const rows = [
      makeRecord({ id: "old", postedDate: "2026-04-09" }),
      makeRecord({ id: "new", postedDate: "2026-07-16" }),
      makeRecord({ id: "mid", postedDate: "2026-05-27" }),
    ];
    expect(byDateDesc(rows).map((r) => r.id)).toEqual(["new", "mid", "old"]);
  });

  it("falls back to screenedDate, then createdAt, when no posted date exists", () => {
    expect(
      orderingDate(makeRecord({ postedDate: "2026-07-01", screenedDate: "2026-08-01" })),
    ).toBe("2026-07-01");
    expect(orderingDate(makeRecord({ postedDate: "", screenedDate: "2026-08-01" }))).toBe(
      "2026-08-01",
    );
    expect(
      orderingDate(
        makeRecord({ postedDate: "", screenedDate: "", createdAt: "2026-08-24T18:00:00Z" }),
      ),
    ).toBe("2026-08-24T18:00:00Z");
  });

  it("does not mutate the array it is given", () => {
    const rows = [
      makeRecord({ id: "a", postedDate: "2026-04-09" }),
      makeRecord({ id: "b", postedDate: "2026-07-16" }),
    ];
    byDateDesc(rows);
    expect(rows.map((r) => r.id)).toEqual(["a", "b"]);
  });

  it("puts a record with no date at all last", () => {
    const rows = [
      makeRecord({ id: "none", postedDate: "", screenedDate: "", createdAt: "" }),
      makeRecord({ id: "dated", postedDate: "2026-04-09" }),
    ];
    expect(byDateDesc(rows).map((r) => r.id)).toEqual(["dated", "none"]);
  });

  it("renders the Found tab newest first", async () => {
    await renderPage([
      makeRecord({ id: "old", company: "OldCo", postedDate: "2026-04-09" }),
      makeRecord({ id: "new", company: "NewCo", postedDate: "2026-07-16" }),
    ]);
    const text = document.body.textContent ?? "";
    expect(text.indexOf("NewCo")).toBeLessThan(text.indexOf("OldCo"));
  });
});

describe("applying by hand from the Found tab", () => {
  it("creates the application and drops the row from Found", async () => {
    vi.mocked(markScreeningApplied).mockResolvedValue({ id: "app1" } as never);
    await renderPage([
      makeRecord({ id: "p1", company: "Camunda" }),
      makeRecord({ id: "p2", company: "Pleo" }),
    ]);

    fireEvent.click(screen.getAllByRole("button", { name: "I applied" })[0]);

    await waitFor(() => expect(markScreeningApplied).toHaveBeenCalledWith("p1"));
    await waitFor(() => expect(screen.queryByText("Camunda")).toBeNull());
    expect(screen.getByText("Pleo")).toBeTruthy();
  });

  it("confirms where the posting went", async () => {
    vi.mocked(markScreeningApplied).mockResolvedValue({ id: "app1" } as never);
    await renderPage([makeRecord({ id: "p1", company: "Camunda" })]);

    fireEvent.click(screen.getByRole("button", { name: "I applied" }));

    expect(await screen.findByText("Added to the Applications page.")).toBeTruthy();
  });

  it("is available without a cover-letter draft, unlike Approve", async () => {
    // The operator already applied; the draft gate does not apply to them.
    await renderPage([makeRecord({ id: "p1", company: "Camunda" })]);

    const applied = screen.getByRole("button", { name: "I applied" }) as HTMLButtonElement;
    const approve = screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement;
    expect(applied.disabled).toBe(false);
    expect(approve.disabled).toBe(true);
  });

  it("keeps the row and surfaces the error when the call fails", async () => {
    vi.mocked(markScreeningApplied).mockRejectedValue(new Error("already applied"));
    await renderPage([makeRecord({ id: "p1", company: "Camunda" })]);

    fireEvent.click(screen.getByRole("button", { name: "I applied" }));

    await waitFor(() => expect(screen.getByText(/already applied/)).toBeTruthy());
    expect(screen.getByText("Camunda")).toBeTruthy();
  });
});
