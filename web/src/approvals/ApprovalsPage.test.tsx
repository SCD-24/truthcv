// @vitest-environment jsdom
/** Approvals page: the operator's queue. Stubbing follows ScreeningsPage.test.tsx. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  bulkSetApproval,
  listApprovedApplications,
  listPendingApprovals,
  setScreeningApproval,
} from "../api/client";
import type { ScreeningRecord } from "../api/types";
import { ApprovalsPage } from "./ApprovalsPage";

vi.mock("../api/client", () => ({
  listPendingApprovals: vi.fn(),
  listApprovedApplications: vi.fn(),
  setScreeningApproval: vi.fn(),
  bulkSetApproval: vi.fn(),
  setCompanyApproval: vi.fn(),
}));

afterEach(cleanup);

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
    vi.mocked(setScreeningApproval).mockResolvedValue(makeRecord({ approval: "approved" }));
    await renderPage([makeRecord()]);
    fireEvent.click(await screen.findByRole("button", { name: /^approve$/i }));
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
});
