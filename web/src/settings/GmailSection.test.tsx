// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import {
  dismissGmailSuggestions,
  listGmailSuggestions,
  getGmailStatus,
  getJevSettings,
  saveJevSettings,
  startGmailLogin,
  syncGmailResponses,
} from "../api/client";
import type { GmailStatus, GmailSuggestion, JevSettings } from "../api/types";
import { GmailSection } from "./GmailSection";

/**
 * Mirrors JevSection.test.tsx's boundary choice — mock the API client
 * module directly rather than stubbing fetch.
 */
vi.mock("../api/client", () => ({
  getJevSettings: vi.fn(),
  getGmailStatus: vi.fn(),
  saveJevSettings: vi.fn(),
  startGmailLogin: vi.fn(),
  syncGmailResponses: vi.fn(),
  listGmailSuggestions: vi.fn(),
  dismissGmailSuggestions: vi.fn(),
}));

function makeSuggestion(id: string, subject: string): GmailSuggestion {
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
    suggested_status: "rejected",
    match_confidence: "high",
    match_evidence: [],
    state: "pending",
    decision: "",
  };
}

async function renderWithRows() {
  vi.mocked(getJevSettings).mockResolvedValueOnce(
    makeJev({ keySet: true, useForEmailTracking: true }),
  );
  vi.mocked(getGmailStatus).mockResolvedValueOnce(
    makeGmail({ connected: true, email: "person@example.com" }),
  );
  vi.mocked(listGmailSuggestions).mockResolvedValue({
    items: [makeSuggestion("id", "Your application")],
    total: 1,
  });
  vi.mocked(dismissGmailSuggestions).mockResolvedValue({ dismissed: 1, pending: 0 });
  render(<GmailSection />);
  await screen.findByText("Your application");
}

function makeJev(overrides: Partial<JevSettings> = {}): JevSettings {
  return {
    keySet: false,
    useForScreening: false,
    useForEmailTracking: false,
    encryptionAvailable: true,
    ...overrides,
  };
}

function makeGmail(overrides: Partial<GmailStatus> = {}): GmailStatus {
  return {
    connected: false,
    email: null,
    reauthRequired: false,
    trackingEnabled: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(listGmailSuggestions).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(dismissGmailSuggestions).mockResolvedValue({ dismissed: 0, pending: 0 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("GmailSection", () => {
  it("no Jev key saved: shows a locked explanation instead of the checkbox", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(makeJev({ keySet: false }));
    vi.mocked(getGmailStatus).mockResolvedValueOnce(makeGmail());
    render(<GmailSection />);

    await screen.findByText(/save a jev api key/i);
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /connect gmail/i })).toBeNull();
  });

  it("key saved: toggling the checkbox calls saveJevSettings with {useForEmailTracking: true}", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(
      makeJev({ keySet: true, useForEmailTracking: false }),
    );
    vi.mocked(getGmailStatus).mockResolvedValueOnce(makeGmail());
    vi.mocked(saveJevSettings).mockResolvedValueOnce(
      makeJev({ keySet: true, useForEmailTracking: true }),
    );
    render(<GmailSection />);

    const checkbox = await screen.findByRole("checkbox", {
      name: /enable email response tracking/i,
    });
    fireEvent.click(checkbox);

    await vi.waitFor(() => {
      expect(saveJevSettings).toHaveBeenCalledWith({ useForEmailTracking: true });
    });
  });

  it("connect button requests an authUrl and navigates to it", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(
      makeJev({ keySet: true, useForEmailTracking: true }),
    );
    vi.mocked(getGmailStatus).mockResolvedValueOnce(makeGmail());
    vi.mocked(startGmailLogin).mockResolvedValueOnce({
      authUrl: "https://accounts.google.com/o/oauth2/auth?foo=bar",
    });

    const originalLocation = window.location;
    // jsdom's window.location isn't configurable for direct assignment;
    // replace it with a plain writable object for this test only.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, href: "" },
    });

    render(<GmailSection />);

    const button = await screen.findByRole("button", { name: /connect gmail/i });
    fireEvent.click(button);

    await vi.waitFor(() => {
      expect(startGmailLogin).toHaveBeenCalled();
      expect(window.location.href).toBe("https://accounts.google.com/o/oauth2/auth?foo=bar");
    });

    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("connect button is disabled until email response tracking is enabled", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(
      makeJev({ keySet: true, useForEmailTracking: false }),
    );
    vi.mocked(getGmailStatus).mockResolvedValueOnce(makeGmail());
    render(<GmailSection />);

    const button = (await screen.findByRole("button", {
      name: /connect gmail/i,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("reauthRequired shows a reconnect prompt", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(
      makeJev({ keySet: true, useForEmailTracking: true }),
    );
    vi.mocked(getGmailStatus).mockResolvedValueOnce(
      makeGmail({ connected: true, email: "person@example.com", reauthRequired: true }),
    );
    render(<GmailSection />);

    expect(await screen.findByText(/needs to be reconnected/i)).toBeTruthy();
    expect(await screen.findByRole("button", { name: /reconnect gmail/i })).toBeTruthy();
  });

  it("connected: shows the connected account email", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(
      makeJev({ keySet: true, useForEmailTracking: true }),
    );
    vi.mocked(getGmailStatus).mockResolvedValueOnce(
      makeGmail({ connected: true, email: "person@example.com" }),
    );
    render(<GmailSection />);

    expect(await screen.findByText(/person@example\.com/)).toBeTruthy();
  });

  it("connected: Sync now button syncs and shows the summary", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(
      makeJev({ keySet: true, useForEmailTracking: true }),
    );
    vi.mocked(getGmailStatus).mockResolvedValueOnce(
      makeGmail({ connected: true, email: "person@example.com" }),
    );
    vi.mocked(syncGmailResponses).mockResolvedValueOnce({
      skipped: false,
      last_synced_at: 1700000000,
      processed: 3,
      suggestions: 2,
    });
    render(<GmailSection />);

    const button = await screen.findByRole("button", { name: /sync now/i });
    fireEvent.click(button);

    await vi.waitFor(() => {
      expect(syncGmailResponses).toHaveBeenCalled();
    });
    expect(await screen.findByText(/scanned 3 new messages/i)).toBeTruthy();
    expect(await screen.findByText(/2 suggestions pending/i)).toBeTruthy();
  });

  it("not connected: Sync now button is not rendered", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(
      makeJev({ keySet: true, useForEmailTracking: true }),
    );
    vi.mocked(getGmailStatus).mockResolvedValueOnce(makeGmail({ connected: false }));
    render(<GmailSection />);

    await screen.findByRole("button", { name: /connect gmail/i });
    expect(screen.queryByRole("button", { name: /sync now/i })).toBeNull();
  });

  it("renders suggestion rows", async () => {
    await renderWithRows();
    expect(screen.getByText(/Acme — Engineer/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Dismiss suggestion: Your application" })).toBeTruthy();
  });

  it("per-row Dismiss calls dismiss and reloads", async () => {
    await renderWithRows();
    const before = vi.mocked(listGmailSuggestions).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Dismiss suggestion: Your application" }));
    await vi.waitFor(() => {
      expect(dismissGmailSuggestions).toHaveBeenCalledWith(["id"]);
      expect(vi.mocked(listGmailSuggestions).mock.calls.length).toBeGreaterThan(before);
    });
  });

  it("bulk dismiss requires confirmation", async () => {
    await renderWithRows();
    fireEvent.click(screen.getByRole("button", { name: /dismiss all on this page/i }));
    expect(dismissGmailSuggestions).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toMatch(/Dismiss 1 suggestion\?/);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Dismiss" }));
    await vi.waitFor(() => {
      expect(dismissGmailSuggestions).toHaveBeenCalledWith(["id"]);
    });
  });

  it("steps back a page when the server reports no rows left on it", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(
      makeJev({ keySet: true, useForEmailTracking: true }),
    );
    vi.mocked(getGmailStatus).mockResolvedValueOnce(makeGmail({ connected: true }));
    vi.mocked(listGmailSuggestions).mockImplementation(async (_limit, offset) => ({
      items: [makeSuggestion(`id${offset}`, `Subject ${offset}`)],
      total: 21,
    }));
    vi.mocked(dismissGmailSuggestions).mockResolvedValue({ dismissed: 1, pending: 20 });
    render(<GmailSection />);
    await screen.findByText("Subject 0");
    fireEvent.click(screen.getByRole("button", { name: /next page/i }));
    await screen.findByText("Subject 20");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss suggestion: Subject 20" }));
    await screen.findByText("Subject 0");
    const calls = vi.mocked(listGmailSuggestions).mock.calls;
    expect(calls[calls.length - 1]).toEqual([20, 0]);
  });

  it("shows the empty state", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(
      makeJev({ keySet: true, useForEmailTracking: true }),
    );
    vi.mocked(getGmailStatus).mockResolvedValueOnce(makeGmail({ connected: true }));
    render(<GmailSection />);
    expect(await screen.findByText("No pending suggestions.")).toBeTruthy();
  });

  it("sync failure shows the error alert", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(
      makeJev({ keySet: true, useForEmailTracking: true }),
    );
    vi.mocked(getGmailStatus).mockResolvedValueOnce(
      makeGmail({ connected: true, email: "person@example.com" }),
    );
    vi.mocked(syncGmailResponses).mockRejectedValueOnce(new Error("Couldn't sync Gmail responses."));
    render(<GmailSection />);

    const button = await screen.findByRole("button", { name: /sync now/i });
    fireEvent.click(button);

    expect(await screen.findByText(/couldn't sync gmail responses/i)).toBeTruthy();
  });
});
