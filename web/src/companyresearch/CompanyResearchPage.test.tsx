// @vitest-environment jsdom
/** Company Research page: findings, contradictions, and the add form.
 * Stubbing follows ScreeningsPage.test.tsx — mock the API client directly. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  createCompanyFinding,
  listCompanyFindings,
  listContradictions,
  resolveCompanyFinding,
} from "../api/client";
import type { CompanyFinding, ContradictionGroup } from "../api/types";
import { CompanyResearchPage } from "./CompanyResearchPage";

vi.mock("../api/client", () => ({
  listCompanyFindings: vi.fn(),
  listContradictions: vi.fn(),
  createCompanyFinding: vi.fn(),
  resolveCompanyFinding: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  vi.mocked(listCompanyFindings).mockResolvedValue([]);
  vi.mocked(listContradictions).mockResolvedValue([]);
});

/** A finding shaped like the backend's camelCase serialisation. */
function makeFinding(overrides: Partial<CompanyFinding> = {}): CompanyFinding {
  return {
    id: "f1",
    company: "Acme Corp",
    claim: "headcount",
    value: "500",
    sourceUrl: "https://acme.example/about",
    sourceClass: "company_statement",
    asOf: "2024-01-01",
    observedAt: "2024-06-01T12:00:00+00:00",
    recordedBy: "operator",
    note: "",
    contradicts: [],
    resolution: "",
    resolvedAt: "",
    resolutionNote: "",
    ...overrides,
  };
}

describe("CompanyResearchPage", () => {
  it("renders both sides of an open contradiction together, each with Accept/Reject", async () => {
    const a = makeFinding({
      id: "a",
      claim: "headcount",
      value: "500",
      sourceClass: "company_statement",
    });
    const b = makeFinding({
      id: "b",
      claim: "headcount",
      value: "2000",
      sourceClass: "audited_accounts",
    });
    vi.mocked(listCompanyFindings).mockResolvedValue([a, b]);
    const group: ContradictionGroup = { claim: "headcount", findings: [a, b] };
    vi.mocked(listContradictions).mockResolvedValue([group]);

    render(<CompanyResearchPage />);

    expect(await screen.findByText("500")).toBeTruthy();
    expect(screen.getByText("2000")).toBeTruthy();
    expect(screen.getByText(/Open contradiction/i)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Accept" })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Reject" })).toHaveLength(2);
  });

  it("resolves a contested finding when Accept is clicked, strongest source first", async () => {
    const weak = makeFinding({ id: "weak", value: "500", sourceClass: "review_site" });
    const strong = makeFinding({ id: "strong", value: "2000", sourceClass: "audited_accounts" });
    vi.mocked(listCompanyFindings).mockResolvedValue([weak, strong]);
    vi.mocked(listContradictions).mockResolvedValue([
      { claim: "headcount", findings: [weak, strong] },
    ]);
    vi.mocked(resolveCompanyFinding).mockResolvedValue(strong);

    render(<CompanyResearchPage />);
    await screen.findByText("2000");

    // Strongest source (audited_accounts → value 2000) renders before the weak one.
    const body = document.body.textContent ?? "";
    expect(body.indexOf("2000")).toBeLessThan(body.indexOf("500"));

    fireEvent.click(screen.getAllByRole("button", { name: "Accept" })[0]);
    await waitFor(() =>
      expect(resolveCompanyFinding).toHaveBeenCalledWith("strong", "accepted"),
    );
  });

  it("refuses to submit the add form with an empty source URL", async () => {
    render(<CompanyResearchPage />);
    // Wait for the initial load to settle so the form is interactive.
    await waitFor(() => expect(listCompanyFindings).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Record finding" }));

    expect(await screen.findByText(/source URL is required/i)).toBeTruthy();
    expect(createCompanyFinding).not.toHaveBeenCalled();
  });

  it("submits the add form when a source URL is present", async () => {
    vi.mocked(createCompanyFinding).mockResolvedValue(makeFinding());
    render(<CompanyResearchPage />);
    await waitFor(() => expect(listCompanyFindings).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Company"), { target: { value: "Globex" } });
    fireEvent.change(screen.getByLabelText("Claim"), { target: { value: "revenue" } });
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "1M" } });
    fireEvent.change(screen.getByLabelText("Source URL"), {
      target: { value: "https://globex.example/ir" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Record finding" }));

    await waitFor(() =>
      expect(createCompanyFinding).toHaveBeenCalledWith(
        expect.objectContaining({
          company: "Globex",
          claim: "revenue",
          value: "1M",
          sourceUrl: "https://globex.example/ir",
        }),
      ),
    );
  });

  it("renders the literal 'unknown' when a finding's as-of is empty", async () => {
    vi.mocked(listCompanyFindings).mockResolvedValue([
      makeFinding({ id: "f1", asOf: "", observedAt: "2024-06-01T12:00:00+00:00" }),
    ]);

    render(<CompanyResearchPage />);

    expect(await screen.findByText("unknown")).toBeTruthy();
  });
});
