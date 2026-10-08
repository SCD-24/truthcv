// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  acceptGmailSuggestion,
  dismissGmailSuggestions,
  getGmailStatus,
  getJevSettings,
  listGmailSuggestions,
} from "../api/client";
import type { GmailSuggestion } from "../api/types";
import { EmailResponsesPage } from "./EmailResponsesPage";

vi.mock("../api/client", () => ({
  getJevSettings: vi.fn(),
  getGmailStatus: vi.fn(),
  listGmailSuggestions: vi.fn(),
  dismissGmailSuggestions: vi.fn(),
  acceptGmailSuggestion: vi.fn(),
}));

function makeItem(id: string, subject: string, over: Partial<GmailSuggestion> = {}): GmailSuggestion {
  return {
    id,
    application_id: "app1",
    application_label: "Acme — Engineer",
    sender: "Recruiter",
    sender_email: "r@acme.com",
    subject,
    date: "2024-01-02",
    snippet: "",
    classification: "rejection",
    suggested_status: "Rejected",
    match_confidence: "high",
    match_evidence: [],
    state: "pending",
    decision: "",
    ...over,
  };
}

function setup(on = true) {
  vi.mocked(getJevSettings).mockResolvedValue({
    keySet: true,
    useForScreening: false,
    useForEmailTracking: on,
    encryptionAvailable: true,
  });
  vi.mocked(getGmailStatus).mockResolvedValue({
    connected: true,
    email: "p@example.com",
    reauthRequired: false,
    trackingEnabled: on,
  });
}

async function renderRows(items = [makeItem("id", "Your application")]) {
  setup();
  vi.mocked(listGmailSuggestions).mockResolvedValue({ items, total: items.length });
  vi.mocked(dismissGmailSuggestions).mockResolvedValue({ dismissed: 1, pending: 0 });
  vi.mocked(acceptGmailSuggestion).mockResolvedValue({
    suggestion: items[0],
    pending: 0,
  });
  render(
    <MemoryRouter>
      <EmailResponsesPage />
    </MemoryRouter>,
  );
  await screen.findByText(items[0].subject);
}

beforeEach(() => {
  vi.mocked(listGmailSuggestions).mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("EmailResponsesPage", () => {
  it("renders rows with label and classification line", async () => {
    await renderRows();
    expect(screen.getByText(/Acme — Engineer/)).toBeTruthy();
    expect(screen.getByText(/Rejection · high confidence/)).toBeTruthy();
  });

  it("accept applies, reloads and announces", async () => {
    await renderRows();
    vi.mocked(listGmailSuggestions).mockResolvedValue({ items: [], total: 0 });
    fireEvent.click(screen.getByRole("button", { name: "Mark Rejected: Your application" }));
    await waitFor(() => expect(acceptGmailSuggestion).toHaveBeenCalledWith("id"));
    await waitFor(() => expect(listGmailSuggestions).toHaveBeenCalledTimes(2));
    await screen.findByText("No email responses to review.");
    expect(screen.getByText("Marked Acme as Rejected")).toBeTruthy();
  });

  it("keeps the company when it contains a separator", async () => {
    await renderRows([makeItem("id", "Hi", { application_label: "Acme — Labs — Engineer" })]);
    fireEvent.click(screen.getByRole("button", { name: "Mark Rejected: Hi" }));
    await screen.findByText("Marked Acme — Labs as Rejected");
  });

  it("reloads after a failed accept", async () => {
    await renderRows();
    vi.mocked(acceptGmailSuggestion).mockRejectedValue(new Error("Already handled"));
    fireEvent.click(screen.getByRole("button", { name: "Mark Rejected: Your application" }));
    await screen.findByText("Already handled");
    await waitFor(() => expect(listGmailSuggestions).toHaveBeenCalledTimes(2));
  });

  it("shows only the error when the initial load fails", async () => {
    setup();
    vi.mocked(listGmailSuggestions).mockRejectedValue(new Error("Load boom"));
    render(
      <MemoryRouter>
        <EmailResponsesPage />
      </MemoryRouter>,
    );
    await screen.findByText("Load boom");
    expect(screen.queryByText("No email responses to review.")).toBeNull();
  });

  it("announces the accepted status while rows remain", async () => {
    await renderRows([makeItem("id", "First"), makeItem("id2", "Second")]);
    fireEvent.click(screen.getByRole("button", { name: "Mark Rejected: First" }));
    await screen.findByText("Marked Acme as Rejected");
  });

  it("has no accept button when there is no suggested status", async () => {
    await renderRows([
      makeItem("id", "Newsletter", { classification: "other", suggested_status: "" }),
    ]);
    expect(screen.queryByRole("button", { name: /^Mark / })).toBeNull();
    expect(screen.getByRole("button", { name: "Dismiss: Newsletter" })).toBeTruthy();
  });

  it("per-row dismiss calls dismiss and reloads", async () => {
    await renderRows();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss: Your application" }));
    await waitFor(() => expect(dismissGmailSuggestions).toHaveBeenCalledWith(["id"]));
    await waitFor(() => expect(listGmailSuggestions).toHaveBeenCalledTimes(2));
  });

  it("bulk dismiss requires confirmation and warns about status changes", async () => {
    await renderRows();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss all on this page" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Dismiss 1 email response?")).toBeTruthy();
    expect(
      within(dialog).getByText(
        "1 of these would change an application's status. Dismissing them means you'll update those applications yourself.",
      ),
    ).toBeTruthy();
    expect(dismissGmailSuggestions).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(dismissGmailSuggestions).toHaveBeenCalledWith(["id"]));
  });

  it("bulk dialog shows plain text when no item has a suggested status", async () => {
    await renderRows([makeItem("id", "Note", { classification: "other", suggested_status: "" })]);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss all on this page" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("These email responses will no longer be shown.")).toBeTruthy();
  });

  it("steps back a page when the server reports no rows left", async () => {
    setup();
    vi.mocked(listGmailSuggestions).mockImplementation(async (_l, offset) =>
      offset === 0
        ? { items: [makeItem("a", "Page one")], total: 21 }
        : { items: [makeItem("b", "Page two")], total: 21 },
    );
    vi.mocked(dismissGmailSuggestions).mockResolvedValue({ dismissed: 1, pending: 20 });
    render(
      <MemoryRouter>
        <EmailResponsesPage />
      </MemoryRouter>,
    );
    await screen.findByText("Page one");
    fireEvent.click(screen.getByRole("button", { name: "Go to next page" }));
    await screen.findByText("Page two");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss: Page two" }));
    await screen.findByText("Page one");
    expect(listGmailSuggestions).toHaveBeenLastCalledWith(20, 0);
  });

  it("tracking off shows the explanation and a Settings link", async () => {
    setup(false);
    const onOpen = vi.fn();
    render(
      <MemoryRouter>
        <EmailResponsesPage onOpenSettings={onOpen} />
      </MemoryRouter>,
    );
    await screen.findByText("Email response tracking is off");
    fireEvent.click(screen.getByText("Open Settings"));
    expect(onOpen).toHaveBeenCalled();
    expect(listGmailSuggestions).not.toHaveBeenCalled();
  });

  it("empty list shows the empty state", async () => {
    setup();
    render(
      <MemoryRouter>
        <EmailResponsesPage />
      </MemoryRouter>,
    );
    await screen.findByText("No email responses to review.");
  });
});
