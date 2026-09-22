// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { getJevSettings, saveJevSettings, testJevKey } from "../api/client";
import type { JevSettings } from "../api/types";
import { JevSection } from "./JevSection";

/**
 * Mirrors AccountsSection.test.tsx's boundary choice — mock the API client
 * module directly rather than stubbing fetch.
 */
vi.mock("../api/client", () => ({
  getJevSettings: vi.fn(),
  saveJevSettings: vi.fn(),
  testJevKey: vi.fn(),
}));

function makeSettings(overrides: Partial<JevSettings> = {}): JevSettings {
  return {
    keySet: false,
    useForScreening: false,
    encryptionAvailable: true,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("JevSection", () => {
  it("no key saved: the 'Use Jev for screening' checkbox is disabled", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(makeSettings({ keySet: false }));
    render(<JevSection />);

    // Plain `.disabled` rather than jest-dom's toBeDisabled: this project
    // does not install @testing-library/jest-dom, so that matcher is undefined.
    const checkbox = (await screen.findByRole("checkbox", {
      name: /use jev for screening/i,
    })) as HTMLInputElement;
    expect(checkbox.disabled).toBe(true);
  });

  it("key saved: the checkbox is enabled", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(makeSettings({ keySet: true }));
    render(<JevSection />);

    const checkbox = (await screen.findByRole("checkbox", {
      name: /use jev for screening/i,
    })) as HTMLInputElement;
    expect(checkbox.disabled).toBe(false);
  });

  it("toggling the checkbox calls saveJevSettings with {useForScreening: true}", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(
      makeSettings({ keySet: true, useForScreening: false }),
    );
    vi.mocked(saveJevSettings).mockResolvedValueOnce(
      makeSettings({ keySet: true, useForScreening: true }),
    );
    render(<JevSection />);

    const checkbox = await screen.findByRole("checkbox", { name: /use jev for screening/i });
    fireEvent.click(checkbox);

    await vi.waitFor(() => {
      expect(saveJevSettings).toHaveBeenCalledWith({ useForScreening: true });
    });
  });

  it("key saved: shows a 'Key saved' state instead of pre-filling the field", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(makeSettings({ keySet: true }));
    render(<JevSection />);

    await screen.findByText(/key saved/i);
    const field = screen.getByLabelText(/jev api key/i) as HTMLInputElement;
    expect(field.value).toBe("");
  });

  it("Test button calls testJevKey and shows the ok/detail result", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(makeSettings({ keySet: true }));
    vi.mocked(testJevKey).mockResolvedValueOnce({ ok: true, detail: "Connected fine." });
    render(<JevSection />);

    fireEvent.click(await screen.findByRole("button", { name: /test key/i }));

    expect(await screen.findByText("Connected fine.")).toBeTruthy();
  });

  it("saving an empty field clears the key", async () => {
    vi.mocked(getJevSettings).mockResolvedValueOnce(makeSettings({ keySet: true }));
    vi.mocked(saveJevSettings).mockResolvedValueOnce(makeSettings({ keySet: false }));
    render(<JevSection />);

    fireEvent.click(await screen.findByRole("button", { name: /save key/i }));

    await vi.waitFor(() => {
      expect(saveJevSettings).toHaveBeenCalledWith({ apiKey: "" });
    });
  });
});
