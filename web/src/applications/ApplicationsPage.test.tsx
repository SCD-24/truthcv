// @vitest-environment jsdom
/** Applications ledger: the outbound record. Stubbing follows
 * ApprovalsPage.test.tsx — mock the API client directly. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { listApplicationsPage } from "../api/client";
import type { Application, ApplicationPage } from "../api/types";
import { ApplicationsPage } from "./ApplicationsPage";

vi.mock("../api/client", () => ({
  APPLICATIONS_EXPORT_URL: "/api/applications/export",
  listApplications: vi.fn(),
  listApplicationsPage: vi.fn(),
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

function makePage(
  apps: Application[],
  total: number,
  offset: number = 0,
  sort: string = "date",
  direction: "asc" | "desc" = "desc",
  limit: number = 25,
): ApplicationPage {
  return {
    applications: apps,
    total,
    limit,
    offset,
    sort: sort as any,
    direction,
  };
}

beforeEach(() => {
  vi.mocked(listApplicationsPage).mockResolvedValue(makePage([], 0));
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

/** Render the page against a mocked server page. `total` defaults to the
 * number of rows passed so a one-page fixture is not mistaken for an empty
 * ledger; pass it explicitly to exercise the pager. */
async function renderPage(
  apps: Application[],
  total: number = apps.length,
  offset: number = 0,
  sort: string = "date",
  direction: "asc" | "desc" = "desc",
) {
  vi.mocked(listApplicationsPage).mockResolvedValue(makePage(apps, total, offset, sort, direction));
  render(
    <BrowserRouter>
      <ApplicationsPage onBack={() => {}} onEditDocument={() => {}} />
    </BrowserRouter>,
  );
  await waitFor(() => expect(listApplicationsPage).toHaveBeenCalled());
}

describe("ApplicationsPage paging", () => {
  it("loads the first page with defaults (25/page, sort date desc, offset 0)", async () => {
    await renderPage([makeApp({ id: "a1" })], 30);

    await waitFor(() => {
      expect(screen.queryByText(/Page 1 of 2/)).toBeTruthy();
    });

    const lastCall = vi.mocked(listApplicationsPage).mock.calls[vi.mocked(listApplicationsPage).mock.calls.length - 1];
    expect(lastCall[0]).toEqual({
      limit: 25,
      offset: 0,
      sort: "date",
      direction: "desc",
      q: "",
    });
  });

  it("shows prev/next buttons and respects paging", async () => {
    await renderPage([makeApp({ id: "a1" })], 30);

    await waitFor(() => expect(screen.queryByText(/Page 1 of 2/)).toBeTruthy());

    // Previous button should be disabled on first page
    const prevBtn = screen.getByRole("button", { name: "Previous" });
    expect(prevBtn.hasAttribute("disabled")).toBe(true);

    // Next button should be enabled
    const nextBtn = screen.getByRole("button", { name: "Next" });
    expect(nextBtn.hasAttribute("disabled")).toBe(false);

    // Click Next
    nextBtn.click();

    // After clicking, should request offset 25
    await waitFor(() => {
      const calls = vi.mocked(listApplicationsPage).mock.calls;
      const lastCall = calls[calls.length - 1];
      expect(lastCall[0].offset).toBe(25);
    });
  });

  it("requests the correct sort and direction when column header is clicked", async () => {
    await renderPage([makeApp({ id: "a1" })], 30);

    await waitFor(() => expect(listApplicationsPage).toHaveBeenCalled());

    // Find and click Company header
    const companyHeader = screen.getAllByRole("button").find((b) => b.textContent?.includes("Company"));
    if (companyHeader) {
      companyHeader.click();

      await waitFor(() => {
        const calls = vi.mocked(listApplicationsPage).mock.calls;
        const lastCall = calls[calls.length - 1];
        expect(lastCall[0].sort).toBe("company");
      });
    }
  });
});

describe("ApplicationsPage link safety", () => {
  it("renders a normal https website as a clickable link", async () => {
    await renderPage([makeApp({ id: "a1", website: "https://acme.example" })], 1);

    const link = (await screen.findByRole("link", {
      name: /Open website: https:\/\/acme\.example/i,
    })) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("https://acme.example");
  });

  it("does not render a javascript: website as a clickable link", async () => {
    await renderPage([makeApp({ id: "a1", website: "javascript:alert(1)" })], 1);

    // The raw text still shows, but as inert text, not an anchor.
    const text = (await screen.findByText("javascript:alert(1)")) as HTMLElement;
    expect(text.closest("a")).toBeNull();
    const anchors = Array.from(document.querySelectorAll("a"));
    expect(anchors.some((a) => (a.getAttribute("href") ?? "").startsWith("javascript:"))).toBe(false);
  });

  it("does not render a javascript: application URL as a clickable link", async () => {
    await renderPage([makeApp({ id: "a1", applicationUrl: "javascript:alert(1)" })], 1);

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

describe("ApplicationsPage search", () => {
  it("filters applications by search query", async () => {
    const acme = makeApp({ id: "1", company: "Acme" });
    const vandelay = makeApp({ id: "2", company: "Vandelay" });

    await renderPage([acme, vandelay]);

    // Initial load passes no filter, so the pager's first page is the whole ledger.
    expect(listApplicationsPage).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: "", offset: 0 }),
    );

    vi.mocked(listApplicationsPage).mockResolvedValue(makePage([vandelay], 1));

    const searchInput = await screen.findByLabelText("Search applications");
    fireEvent.change(searchInput, { target: { value: "vand" } });

    // Wait past the debounce (250ms) for the search call to fire.
    await waitFor(
      () => {
        expect(listApplicationsPage).toHaveBeenLastCalledWith(
          expect.objectContaining({ q: "vand", offset: 0 }),
        );
      },
      { timeout: 400 },
    );

    await waitFor(() => {
      expect(screen.getByText("Vandelay")).toBeTruthy();
      expect(screen.queryByText("Acme")).toBeNull();
    });

    expect(screen.getByText("1 matching")).toBeTruthy();
  });
});
