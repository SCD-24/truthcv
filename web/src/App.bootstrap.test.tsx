// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";
import { WizardProvider } from "./wizard/store";
import { getOnboarding } from "./api/client";

vi.mock("./api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/client")>();
  return {
    ...actual,
    getProfile: vi.fn().mockResolvedValue({ hasProfile: false }),
    getOnboarding: vi.fn(),
    extractTruth: vi.fn().mockResolvedValue({
      experiences: [],
      education: [],
      skills: [],
      hobbies: [],
      profile: { name: "", email: "", phone: "", location: "", links: [], summary: "" },
    }),
    listPendingApprovals: vi.fn().mockResolvedValue([]),
    listApplications: vi.fn().mockResolvedValue([]),
    listConnections: vi.fn().mockResolvedValue({ connections: [] }),
    getRouting: vi.fn().mockResolvedValue({ default: null, agent: null, tasks: {} }),
    updateOnboarding: vi.fn(),
  };
});

function renderApp() {
  return render(
    <WizardProvider>
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    </WizardProvider>,
  );
}

afterEach(cleanup);

describe("App bootstrap failure", () => {
  it("shows a retry screen and no shell when getOnboarding rejects", async () => {
    vi.mocked(getOnboarding).mockRejectedValue(new Error("network down"));
    renderApp();

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("Upload CV")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Analytics" })).toBeNull();
  });

  it("re-fetches on Retry and lands on onboarding for an incomplete state", async () => {
    vi.mocked(getOnboarding).mockRejectedValueOnce(new Error("network down"));
    // OnboardingPage itself calls getOnboarding() again once mounted, so the
    // incomplete state must be the default for every call after the retry,
    // not just a single queued response.
    vi.mocked(getOnboarding).mockResolvedValue({
      providerDone: false,
      hasProfile: false,
      cvReviewedAt: null,
      tourSeenAt: null,
      complete: false,
    });
    renderApp();

    const alert = await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    expect(await screen.findByText(/connect a provider/i)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(alert).toBeTruthy();
    expect(vi.mocked(getOnboarding).mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("never shows the retry screen when getOnboarding resolves on the first call", async () => {
    vi.mocked(getOnboarding).mockResolvedValue({
      providerDone: true,
      hasProfile: true,
      cvReviewedAt: "2024-01-01T00:00:00.000Z",
      tourSeenAt: "2024-01-01T00:00:00.000Z",
      complete: true,
    });
    renderApp();

    expect(await screen.findByRole("heading", { name: "Analytics" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
