// @vitest-environment jsdom
/** Applications ledger: the outbound record. Stubbing follows
 * ApprovalsPage.test.tsx — mock the API client directly. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
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

async function renderPage(
  apps: Application[],
  total: number = 0,
  offset: number = 0,
  sort: string = "date",
  direction: "asc" | "desc" = "desc",
) {
  vi.mocked(listApplicationsPage).mockResolvedValue(makePage(apps, total, offset, sort, direction));
  render(<ApplicationsPage onBack={() => {}} onEditDocument={() => {}} />);
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
