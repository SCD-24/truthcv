// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";
import { WizardProvider } from "./wizard/store";
import { listApplications } from "./api/client";

vi.mock("./api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/client")>();
  return {
    ...actual,
    getProfile: vi.fn().mockResolvedValue({ hasProfile: false }),
    extractTruth: vi.fn().mockResolvedValue({
      experiences: [],
      education: [],
      skills: [],
      profile: { name: "", email: "", phone: "", location: "", links: [], summary: "" },
    }),
    listPendingApprovals: vi.fn().mockResolvedValue([]),
    listApplications: vi.fn().mockResolvedValue([]),
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

  it("shows the Upload step at /cv/upload", async () => {
    renderAt("/cv/upload");
    expect(await screen.findByText("Every line, traceable.")).toBeTruthy();
  });

  it("redirects /cv/confirm with no inferences to Posting", async () => {
    renderAt("/cv/confirm");
    expect(
      await screen.findByText("Paste the job you're after"),
    ).toBeTruthy();
  });
});
