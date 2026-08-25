// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  extractTruth,
  getOnboarding,
  getProfile,
  getTruth,
  saveTruth,
  updateOnboarding,
  uploadPdf,
} from "../api/client";
import type { TruthDoc } from "../api/types";
import { WizardProvider } from "../wizard/store";
import { UploadCvPage } from "./UploadCvPage";

vi.mock("../api/client", () => ({
  extractTruth: vi.fn(),
  getOnboarding: vi.fn(),
  getProfile: vi.fn(),
  getTruth: vi.fn(),
  saveTruth: vi.fn(),
  updateOnboarding: vi.fn(),
  uploadPdf: vi.fn(),
}));

function emptyTruth(): TruthDoc {
  return {
    experiences: [],
    education: [],
    skills: [],
    profile: { name: "", email: "", phone: "", location: "", links: [], summary: "" },
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

vi.mocked(getOnboarding).mockResolvedValue({
  providerDone: true,
  hasProfile: false,
  cvReviewedAt: null,
  tourSeenAt: null,
  complete: false,
});

function renderPage(onDone = vi.fn()) {
  return render(
    <WizardProvider>
      <UploadCvPage onDone={onDone} />
    </WizardProvider>,
  );
}

describe("UploadCvPage", () => {
  it("opens on Upload", async () => {
    vi.mocked(getProfile).mockResolvedValue({ hasProfile: false });
    renderPage();
    expect(await screen.findByText("Drop your LinkedIn PDF here")).toBeTruthy();
  });

  it("shows Review after a successful upload", async () => {
    vi.mocked(getProfile).mockResolvedValue({ hasProfile: false });
    vi.mocked(uploadPdf).mockResolvedValue(undefined);
    vi.mocked(extractTruth).mockResolvedValue(emptyTruth());
    vi.mocked(getTruth).mockResolvedValue(emptyTruth());
    renderPage();
    await screen.findByText("Drop your LinkedIn PDF here");

    const file = new File(["%PDF"], "profile.pdf", { type: "application/pdf" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /continue to review/i }));

    expect(await screen.findByText("Review what we found")).toBeTruthy();
  });

  it("marks the CV reviewed and calls onDone when Review is saved", async () => {
    vi.mocked(getProfile).mockResolvedValue({ hasProfile: false });
    vi.mocked(uploadPdf).mockResolvedValue(undefined);
    vi.mocked(extractTruth).mockResolvedValue(emptyTruth());
    vi.mocked(saveTruth).mockResolvedValue(undefined);
    vi.mocked(updateOnboarding).mockResolvedValue({
      providerDone: true,
      hasProfile: true,
      cvReviewedAt: "2024-01-01T00:00:00.000Z",
      tourSeenAt: null,
      complete: false,
    });
    const onDone = vi.fn();
    renderPage(onDone);
    await screen.findByText("Drop your LinkedIn PDF here");

    const file = new File(["%PDF"], "profile.pdf", { type: "application/pdf" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /continue to review/i }));
    await screen.findByText("Review what we found");

    fireEvent.click(screen.getByRole("button", { name: /save & continue/i }));

    await waitFor(() =>
      expect(updateOnboarding).toHaveBeenCalledWith(
        expect.objectContaining({ cvReviewedAt: expect.any(String) }),
      ),
    );
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });
});
