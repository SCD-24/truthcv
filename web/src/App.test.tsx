// @vitest-environment jsdom
/** Unknown routes render a NotFound view (with a way back to Analytics)
 * instead of silently redirecting there. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";
import { WizardProvider } from "./wizard/store";
import {
  extractTruth,
  getOnboarding,
  getSigninQueue,
  listPendingApprovals,
} from "./api/client";

vi.mock("./api/client", () => ({
  getOnboarding: vi.fn(),
  updateOnboarding: vi.fn(),
  getSigninQueue: vi.fn(),
  listPendingApprovals: vi.fn(),
  extractTruth: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(getOnboarding).mockResolvedValue({
    providerDone: true,
    hasProfile: true,
    cvReviewedAt: "2024-01-01T00:00:00Z",
    tourSeenAt: "2024-01-01T00:00:00Z",
    complete: true,
  });
  vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
  vi.mocked(listPendingApprovals).mockResolvedValue([]);
  vi.mocked(extractTruth).mockResolvedValue({
    experiences: [],
    education: [],
    skills: [],
    hobbies: [],
    profile: { name: "", email: "", phone: "", location: "", links: [], summary: "" },
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <WizardProvider>
        <App />
      </WizardProvider>
    </MemoryRouter>,
  );
}

describe("App routing", () => {
  it("shows a NotFound view for an unknown route, not a silent redirect", async () => {
    renderAt("/this-route-does-not-exist");

    await waitFor(() => {
      expect(screen.getByText(/page not found/i)).toBeTruthy();
    });
    expect(screen.getByRole("button", { name: /go to analytics/i })).toBeTruthy();
  });

  it("still redirects the root path to Analytics", async () => {
    renderAt("/");

    await waitFor(() => {
      expect(screen.queryByText(/page not found/i)).toBeNull();
    });
  });
});
