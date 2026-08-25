// @vitest-environment jsdom
/** Applications ledger: the outbound record. Stubbing follows
 * ApprovalsPage.test.tsx — mock the API client directly. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { listApplications } from "../api/client";
import type { Application } from "../api/types";
import { ApplicationsPage } from "./ApplicationsPage";

vi.mock("../api/client", () => ({
  APPLICATIONS_EXPORT_URL: "/api/applications/export",
  listApplications: vi.fn(),
  createApplication: vi.fn(),
  updateApplication: vi.fn(),
  deleteApplication: vi.fn(),
  saveApplicationCv: vi.fn(),
  saveApplicationCoverLetter: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  vi.mocked(listApplications).mockResolvedValue([]);
});

function makeApp(overrides: Partial<Application> = {}): Application {
  return {
    id: "x",
    company: "Acme",
    website: "",
    applicationUrl: "",
    submitted: false,
    submissionType: "",
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
    ...overrides,
  };
}

async function renderPage(apps: Application[]) {
  vi.mocked(listApplications).mockResolvedValue(apps);
  render(<ApplicationsPage onBack={() => {}} onEditDocument={() => {}} />);
  await waitFor(() => expect(listApplications).toHaveBeenCalled());
}

describe("ApplicationsPage link safety", () => {
  it("renders a normal https website as a clickable link", async () => {
    await renderPage([makeApp({ id: "a1", website: "https://acme.example" })]);

    const link = (await screen.findByRole("link", {
      name: /Open website: https:\/\/acme\.example/i,
    })) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("https://acme.example");
  });

  it("does not render a javascript: website as a clickable link", async () => {
    await renderPage([makeApp({ id: "a1", website: "javascript:alert(1)" })]);

    // The raw text still shows, but as inert text, not an anchor.
    const text = (await screen.findByText("javascript:alert(1)")) as HTMLElement;
    expect(text.closest("a")).toBeNull();
    const anchors = Array.from(document.querySelectorAll("a"));
    expect(anchors.some((a) => (a.getAttribute("href") ?? "").startsWith("javascript:"))).toBe(false);
  });

  it("does not render a javascript: application URL as a clickable link", async () => {
    await renderPage([makeApp({ id: "a1", applicationUrl: "javascript:alert(1)" })]);

    const text = (await screen.findByText("javascript:alert(1)")) as HTMLElement;
    expect(text.closest("a")).toBeNull();
    const anchors = Array.from(document.querySelectorAll("a"));
    expect(anchors.some((a) => (a.getAttribute("href") ?? "").startsWith("javascript:"))).toBe(false);
  });
});
