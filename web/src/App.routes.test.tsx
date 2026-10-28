// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BrowserRouter, MemoryRouter, useNavigate } from "react-router-dom";
import { App } from "./App";
import { WizardProvider } from "./wizard/store";
import { ROUTES } from "./routes";
import { getOnboarding, listApplications } from "./api/client";

vi.mock("./api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/client")>();
  return {
    ...actual,
    getProfile: vi.fn().mockResolvedValue({ hasProfile: false }),
    getOnboarding: vi.fn().mockResolvedValue({
      providerDone: true,
      hasProfile: true,
      cvReviewedAt: "2024-01-01T00:00:00.000Z",
      tourSeenAt: "2024-01-01T00:00:00.000Z",
      complete: true,
    }),
    extractTruth: vi.fn().mockResolvedValue({
      experiences: [],
      education: [],
      skills: [],
      hobbies: [],
      profile: { name: "", email: "", phone: "", location: "", links: [], summary: "" },
    }),
    getTruth: vi.fn().mockResolvedValue({
      experiences: [],
      education: [],
      skills: [],
      hobbies: [],
      profile: { name: "", email: "", phone: "", location: "", links: [], summary: "" },
    }),
    getJevSettings: vi.fn().mockResolvedValue({ keySet: true, useForEmailTracking: true }),
    getGmailStatus: vi.fn().mockResolvedValue({ connected: true }),
    listGmailSuggestions: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    listPendingApprovals: vi.fn().mockResolvedValue([]),
    listApplications: vi.fn().mockResolvedValue([]),
    listConnections: vi.fn().mockResolvedValue({ connections: [] }),
    getRouting: vi.fn().mockResolvedValue({ default: null, agent: null, tasks: {} }),
    updateOnboarding: vi.fn().mockResolvedValue({
      providerDone: true,
      hasProfile: true,
      cvReviewedAt: "2024-01-01T00:00:00.000Z",
      tourSeenAt: "2024-01-01T00:00:00.000Z",
      complete: true,
    }),
  };
});

function renderAt(path: string) {
  return render(
    <WizardProvider>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </WizardProvider>,
  );
}

afterEach(cleanup);

describe("App routing", () => {
  it("shows Analytics at /", async () => {
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Analytics" })).toBeTruthy();
  });

  it("shows the applications ledger at /applications", async () => {
    renderAt("/applications");
    expect(await screen.findByRole("heading", { name: "Applications" })).toBeTruthy();
  });

  it("shows the filled form page at /applications/abc123/filled-form", async () => {
    vi.mocked(listApplications).mockResolvedValueOnce([
      {
        id: "abc123",
        company: "Acme",
        website: "",
        applicationUrl: "",
        submitted: true,
        submissionType: "General",
        reachedOut: false,
        toWho: "",
        responseReceived: false,
        method: "",
        posting: "",
        applicationDate: "",
        status: "",
        notes: "",
        cvDocument: null,
        coverLetterDocument: null,
        createdAt: "",
        updatedAt: "",
        fieldsSubmitted: [{ label: "Full name", value: "Jane Doe", source: "profile" }],
      },
    ]);
    renderAt("/applications/abc123/filled-form");
    expect(await screen.findByText("Jane Doe")).toBeTruthy();
  });

  it("shows the Email responses page at /email-responses", async () => {
    renderAt(ROUTES.emailResponses);
    expect(await screen.findByRole("heading", { name: "Email responses" })).toBeTruthy();
  });

  it("shows the Upload CV page at /cv", async () => {
    renderAt(ROUTES.uploadCv);
    expect(await screen.findByText("Every line, traceable.")).toBeTruthy();
  });

  it("shows the Truth file page at /truth", async () => {
    renderAt(ROUTES.truthFile);
    expect(await screen.findByText("Your truth file")).toBeTruthy();
  });

  it("redirects to Onboarding when onboarding is incomplete", async () => {
    vi.mocked(getOnboarding).mockResolvedValueOnce({
      providerDone: false,
      hasProfile: false,
      cvReviewedAt: null,
      tourSeenAt: null,
      complete: false,
    });
    renderAt(ROUTES.analytics);
    expect(await screen.findByText(/connect a provider/i)).toBeTruthy();
  });

  it("renders Analytics with no tour overlay when the tour was already seen", async () => {
    renderAt(ROUTES.analytics);
    expect(await screen.findByRole("heading", { name: "Analytics" })).toBeTruthy();
    expect(screen.queryByText("Start with Manual")).toBeNull();
  });

  it("shows the tour when onboarding is complete but the tour was never seen", async () => {
    vi.mocked(getOnboarding).mockResolvedValueOnce({
      providerDone: true,
      hasProfile: true,
      cvReviewedAt: "2024-01-01T00:00:00.000Z",
      tourSeenAt: null,
      complete: true,
    });
    renderAt(ROUTES.analytics);
    expect(await screen.findByText("Start with Manual")).toBeTruthy();
  });
});

describe("backslash paths stay on the app origin", () => {
  function NavigateButton({ to }: { to: string }) {
    const navigate = useNavigate();
    return (
      <button
        onClick={() => {
          try {
            void navigate(to);
          } catch {
            // react-router rejects external targets by throwing; the origin check below is what matters.
          }
        }}
      >
        go
      </button>
    );
  }

  it.each(["/\\evil.com", "\\\\evil.com"])("navigate(%j) keeps the app origin", (to) => {
    const start = window.location.href;
    const pushState = vi.spyOn(window.history, "pushState");
    render(
      <BrowserRouter>
        <NavigateButton to={to} />
      </BrowserRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "go" }));
    const pushed = pushState.mock.calls.map(([, , url]) => new URL(String(url), start).origin);
    pushState.mockRestore();
    expect(pushed.filter((origin) => origin !== window.location.origin)).toEqual([]);
    expect(window.location.href).toBe(start);
  });
});
