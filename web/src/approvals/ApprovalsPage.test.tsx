// @vitest-environment jsdom
/** Approvals page: the operator's queue. Stubbing follows ScreeningsPage.test.tsx. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  bulkSetApproval,
  generateScreeningLetter,
  getScreeningLetter,
  listApprovedApplications,
  listDidNotPass,
  listPendingApprovals,
  listRejectedApprovals,
  saveScreeningLetter,
  setScreeningApproval,
  setScreeningUrl,
} from "../api/client";
import type { ScreeningRecord } from "../api/types";
import { ApprovalsPage } from "./ApprovalsPage";

vi.mock("../api/client", () => ({
  listPendingApprovals: vi.fn(),
  listApprovedApplications: vi.fn(),
  listRejectedApprovals: vi.fn(),
  listDidNotPass: vi.fn(),
  setScreeningApproval: vi.fn(),
  bulkSetApproval: vi.fn(),
  setCompanyApproval: vi.fn(),
  setScreeningUrl: vi.fn(),
  getScreeningLetter: vi.fn(),
  generateScreeningLetter: vi.fn(),
  saveScreeningLetter: vi.fn(),
}));

afterEach(cleanup);

// The list endpoint never carries drafts (PendingCard fetches its own), so
// every test needs a stub; the no-draft case is the common one, and the
// cover-letter tests below override it before rendering.
beforeEach(() => {
  vi.mocked(getScreeningLetter).mockResolvedValue(null);
  vi.mocked(listRejectedApprovals).mockResolvedValue([]);
  vi.mocked(listDidNotPass).mockResolvedValue([]);
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

async function renderPage(pending: ScreeningRecord[], approved: ScreeningRecord[] = []) {
  vi.mocked(listPendingApprovals).mockResolvedValue(pending);
  vi.mocked(listApprovedApplications).mockResolvedValue(approved);
  render(<ApprovalsPage onBack={() => {}} />);
  await waitFor(() => expect(listPendingApprovals).toHaveBeenCalled());
}

describe("ApprovalsPage", () => {
  it("renders a pending item with the agent's deferral reason", async () => {
    await renderPage([makeRecord()]);
    expect(await screen.findByText("Grafana Labs")).toBeTruthy();
    expect(screen.getByText(/German hiring entity unverified/)).toBeTruthy();
  });

  it("shows the empty state when nothing is waiting", async () => {
    await renderPage([]);
    expect(await screen.findByText(/nothing waiting/i)).toBeTruthy();
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

  it("shows the blocked claim's text when generation is refused by the guardrail", async () => {
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
  });

  it("shows the posted and found dates", async () => {
    vi.mocked(getScreeningLetter).mockResolvedValue(null);
    await renderPage([makeRecord()]);
    expect(await screen.findByText(/Posted 2026-08-20/)).toBeTruthy();
    expect(screen.getByText(/Found 2026-08-23/)).toBeTruthy();
  });
});

describe("ApprovalsPage reviewable lists", () => {
  it("lists what the agent rejected on a criterion, apart from what you rejected", async () => {
    vi.mocked(listDidNotPass).mockResolvedValue([
      makeRecord({ id: "d1", company: "SumUp", verdict: "rejected", approval: "", failingCriterion: "remote" }),
    ]);
    vi.mocked(listRejectedApprovals).mockResolvedValue([
      makeRecord({ id: "r1", company: "Pleo", approval: "rejected" }),
    ]);
    await renderPage([]);
    expect(await screen.findByRole("heading", { name: "Did not pass" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Rejected" })).toBeTruthy();
    expect(screen.getByText("SumUp")).toBeTruthy();
    expect(screen.getByText("Pleo")).toBeTruthy();
  });

  it("moving one back queues it and takes it out of the list it came from", async () => {
    vi.mocked(listRejectedApprovals).mockResolvedValue([
      makeRecord({ id: "r1", company: "Pleo", approval: "rejected" }),
    ]);
    vi.mocked(setScreeningApproval).mockResolvedValue(
      makeRecord({ id: "r1", company: "Pleo", approval: "pending" }),
    );
    await renderPage([]);
    fireEvent.click(await screen.findByRole("button", { name: "Move to approvals" }));
    await waitFor(() => expect(setScreeningApproval).toHaveBeenCalledWith("r1", "pending"));
    await waitFor(() =>
      expect(screen.queryAllByRole("button", { name: "Move to approvals" }).length).toBe(0),
    );
  });
});
