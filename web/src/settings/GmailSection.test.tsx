// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { getGmailStatus, getJevSettings, saveJevSettings, startGmailLogin } from "../api/client";
import type { GmailStatus, JevSettings } from "../api/types";
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
}));

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
});
