// @vitest-environment jsdom
/** Applications ledger: the outbound record. Stubbing follows
 * ApprovalsPage.test.tsx — mock the API client directly. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
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
  render(
    <BrowserRouter>
      <ApplicationsPage onBack={() => {}} onEditDocument={() => {}} />
    </BrowserRouter>,
  );
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

describe("ApplicationsPage compact row layout", () => {
  it("header has no Website/URL/Documents/Filled form column headers", async () => {
    await renderPage([makeApp({ id: "a1" })]);

    const table = await screen.findByRole("table");
    const header = within(table).getAllByRole("row")[0];
    expect(within(header).queryByText("Website")).toBeNull();
    expect(within(header).queryByText("URL")).toBeNull();
    expect(within(header).queryByText("Documents")).toBeNull();
    expect(within(header).queryByText("Filled form")).toBeNull();

    expect(within(header).getByText("Company")).toBeTruthy();
    expect(within(header).getByText("Date")).toBeTruthy();
    expect(within(header).getByText("Status")).toBeTruthy();
  });

  it("app with posting, cvDocument and fieldsSubmitted shows Posting, CV, Filled form items and + Add cover letter", async () => {
    await renderPage([
      makeApp({
        id: "a1",
        posting: "Senior Engineer",
        cvDocument: {
          source: "<html></html>",
          pdfUrl: "/files/a1-cv.pdf",
          docxUrl: "/files/a1-cv.docx",
          updatedAt: "2026-01-01T00:00:00Z",
        },
        fieldsSubmitted: [{ label: "Full name", value: "Jane Doe", source: "profile" }],
      }),
    ]);

    expect(await screen.findByText("Posting")).toBeTruthy();
    expect(screen.getByText("CV")).toBeTruthy();
    expect(screen.getByText("Filled form")).toBeTruthy();
    expect(screen.getByText("+ Add cover letter")).toBeTruthy();
  });

  it("app with none shows + Add posting, + Add CV, + Add cover letter", async () => {
    await renderPage([
      makeApp({
        id: "a1",
        posting: "",
        cvDocument: null,
        coverLetterDocument: null,
        fieldsSubmitted: [],
      }),
    ]);

    expect(screen.getByText("+ Add posting")).toBeTruthy();
    expect(screen.getByText("+ Add CV")).toBeTruthy();
    expect(screen.getByText("+ Add cover letter")).toBeTruthy();
  });

  it("clicking Posting opens a dialog", async () => {
    await renderPage([makeApp({ id: "a1", posting: "A job posting text" })]);

    const link = await screen.findByText("Posting");
    fireEvent.click(link);

    expect(await screen.findByRole("dialog")).toBeTruthy();
  });
});
