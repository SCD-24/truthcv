// @vitest-environment jsdom
/** Company Research page: cards, contradictions, search, and the dialogs.
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
    companyKey: "acme corp",
    claim: "employment_entity",
    claimLabel: "",
    supersedes: "",
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
    const a = makeFinding({ id: "a", value: "500", sourceClass: "company_statement" });
    const b = makeFinding({ id: "b", value: "2000", sourceClass: "audited_accounts" });
    vi.mocked(listCompanyFindings).mockResolvedValue([a, b]);
    const group: ContradictionGroup = { claim: "employment_entity", findings: [a, b] };
    vi.mocked(listContradictions).mockResolvedValue([group]);

    render(<CompanyResearchPage />);

    expect(await screen.findByText("500")).toBeTruthy();
    expect(screen.getByText("2000")).toBeTruthy();
    expect(screen.getByText(/Open contradiction/i)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Accept" })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Reject" })).toHaveLength(2);
    // The card is flagged for review (chip on the card, plus the filter toggle).
    expect(screen.getAllByText("Needs review").length).toBeGreaterThanOrEqual(2);
  });

  it("resolves a contested finding when Accept is clicked, strongest source first", async () => {
    const weak = makeFinding({ id: "weak", value: "500", sourceClass: "review_site" });
    const strong = makeFinding({ id: "strong", value: "2000", sourceClass: "audited_accounts" });
    vi.mocked(listCompanyFindings).mockResolvedValue([weak, strong]);
    vi.mocked(listContradictions).mockResolvedValue([
      { claim: "employment_entity", findings: [weak, strong] },
    ]);
    vi.mocked(resolveCompanyFinding).mockResolvedValue(strong);

    render(<CompanyResearchPage />);
    await screen.findByText("2000");

    const body = document.body.textContent ?? "";
    expect(body.indexOf("2000")).toBeLessThan(body.indexOf("500"));

    fireEvent.click(screen.getAllByRole("button", { name: "Accept" })[0]);
    await waitFor(() =>
      expect(resolveCompanyFinding).toHaveBeenCalledWith("strong", "accepted"),
    );
  });

  it("adds a finding through the dialog", async () => {
    vi.mocked(createCompanyFinding).mockResolvedValue(makeFinding());
    render(<CompanyResearchPage />);
    await screen.findByText(/No company findings recorded yet/i);

    fireEvent.click(screen.getByRole("button", { name: "Add finding" }));
    fireEvent.change(await screen.findByRole("combobox", { name: /^Company/ }), { target: { value: "Globex" } });
    fireEvent.change(screen.getByLabelText(/^Value/), { target: { value: "Globex AG" } });
    fireEvent.change(screen.getByLabelText(/^Source URL/), {
      target: { value: "https://globex.example/ir" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Add finding" }).pop()!);

    await waitFor(() =>
      expect(createCompanyFinding).toHaveBeenCalledWith(
        expect.objectContaining({
          company: "Globex",
          claim: "employment_entity",
          value: "Globex AG",
          sourceUrl: "https://globex.example/ir",
        }),
      ),
    );
  });

  it("renders a normal https source URL as a clickable link", async () => {
    vi.mocked(listCompanyFindings).mockResolvedValue([
      makeFinding({ id: "f1", sourceUrl: "https://acme.example/about" }),
    ]);

    render(<CompanyResearchPage />);

    const link = (await screen.findByText("https://acme.example/about")) as HTMLElement;
    expect(link.closest("a")?.getAttribute("href")).toBe("https://acme.example/about");
  });

  it("does not render a javascript: source URL as a clickable link", async () => {
    vi.mocked(listCompanyFindings).mockResolvedValue([
      makeFinding({ id: "f1", sourceUrl: "javascript:alert(1)" }),
    ]);

    render(<CompanyResearchPage />);

    const text = (await screen.findByText("javascript:alert(1)")) as HTMLElement;
    expect(text.closest("a")).toBeNull();
    const anchors = Array.from(document.querySelectorAll("a"));
    expect(anchors.some((a) => (a.getAttribute("href") ?? "").startsWith("javascript:"))).toBe(false);
  });

  it("renders the literal 'unknown' when a finding's as-of is empty", async () => {
    vi.mocked(listCompanyFindings).mockResolvedValue([makeFinding({ id: "f1", asOf: "" })]);

    render(<CompanyResearchPage />);

    expect(await screen.findByText("unknown")).toBeTruthy();
  });

  it("filters cards by the search box and shows a no-match state", async () => {
    vi.mocked(listCompanyFindings).mockResolvedValue([
      makeFinding({ id: "a", company: "Acme Corp", companyKey: "acme corp", value: "Acme AG" }),
      makeFinding({ id: "b", company: "Globex", companyKey: "globex", value: "Globex Ltd" }),
    ]);
    render(<CompanyResearchPage />);
    await screen.findByText("Globex");

    fireEvent.change(screen.getByLabelText("Search companies"), { target: { value: "glob" } });
    expect(screen.queryByText("Acme Corp")).toBeNull();
    expect(screen.getByText("Globex")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Search companies"), { target: { value: "zzz" } });
    expect(screen.getByText(/No companies match/i)).toBeTruthy();
    expect(screen.queryByText(/No company findings recorded yet/i)).toBeNull();
  });

  it("groups variant spellings of one company into a single card", async () => {
    vi.mocked(listCompanyFindings).mockResolvedValue([
      makeFinding({
        id: "a",
        company: "Acme GmbH",
        companyKey: "acme",
        claim: "employer_rating",
        value: "4.1",
        observedAt: "2024-01-01T00:00:00+00:00",
      }),
      makeFinding({
        id: "b",
        company: "Acme",
        companyKey: "acme",
        value: "Acme SE",
        observedAt: "2024-05-01T00:00:00+00:00",
      }),
    ]);
    render(<CompanyResearchPage />);

    expect(await screen.findByText("Acme")).toBeTruthy();
    expect(screen.queryByText("Acme GmbH")).toBeNull();
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(1);
    expect(screen.getByText("Employing entity")).toBeTruthy();
    expect(screen.getByText("Employer rating")).toBeTruthy();
  });

  it("shows the current value with superseded history collapsed", async () => {
    vi.mocked(listCompanyFindings).mockResolvedValue([
      makeFinding({ id: "old", value: "Old Name", observedAt: "2024-01-01T00:00:00+00:00" }),
      makeFinding({
        id: "new",
        value: "New Name",
        supersedes: "old",
        observedAt: "2024-05-01T00:00:00+00:00",
      }),
    ]);
    render(<CompanyResearchPage />);

    expect(await screen.findByText("New Name")).toBeTruthy();
    expect(screen.queryByText("Old Name")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "History (1)" }));
    expect(await screen.findByText("Old Name")).toBeTruthy();
  });

  it("opens a prefilled dialog when Correct is clicked", async () => {
    vi.mocked(listCompanyFindings).mockResolvedValue([
      makeFinding({ id: "f1", value: "Acme SE" }),
    ]);
    render(<CompanyResearchPage />);
    await screen.findByText("Acme SE");

    fireEvent.click(screen.getByRole("button", { name: "Correct" }));

    expect(await screen.findByText("Correct finding")).toBeTruthy();
    expect((screen.getByLabelText(/^Value/) as HTMLInputElement).value).toBe("Acme SE");
    expect((screen.getByRole("combobox", { name: /^Company/ }) as HTMLInputElement).disabled).toBe(true);
  });

  it("does not render a mailto: source URL as a link", async () => {
    vi.mocked(listCompanyFindings).mockResolvedValue([
      makeFinding({ id: "f1", sourceUrl: "mailto:a@b.example" }),
    ]);
    render(<CompanyResearchPage />);
    const text = (await screen.findByText("mailto:a@b.example")) as HTMLElement;
    expect(text.closest("a")).toBeNull();
  });

  it("hides Correct for legacy free-text claims", async () => {
    vi.mocked(listCompanyFindings).mockResolvedValue([
      makeFinding({ id: "f1", claim: "headcount" as CompanyFinding["claim"], value: "LegacyVal" }),
    ]);
    render(<CompanyResearchPage />);
    await screen.findByText("LegacyVal");
    expect(screen.queryByRole("button", { name: "Correct" })).toBeNull();
  });

  it("gives Accept/Reject only to cited contenders", async () => {
    const a = makeFinding({ id: "a", value: "AAA", sourceClass: "audited_accounts" });
    const b = makeFinding({ id: "b", value: "BBB", sourceClass: "company_statement" });
    const u = makeFinding({ id: "u", value: "UUU", sourceClass: "unattributed" });
    vi.mocked(listCompanyFindings).mockResolvedValue([a, b, u]);
    vi.mocked(listContradictions).mockResolvedValue([
      { claim: "employment_entity", findings: [a, b] },
    ]);
    render(<CompanyResearchPage />);
    await screen.findByText("AAA");
    expect(screen.getAllByRole("button", { name: "Accept" })).toHaveLength(2);
    expect(screen.queryByText("UUU")).toBeNull();
  });

  it("reports a refetch failure after a successful resolve as a load error", async () => {
    const a = makeFinding({ id: "a", value: "AAA", sourceClass: "audited_accounts" });
    const b = makeFinding({ id: "b", value: "BBB", sourceClass: "company_statement" });
    vi.mocked(listCompanyFindings).mockResolvedValueOnce([a, b]);
    vi.mocked(listContradictions).mockResolvedValueOnce([
      { claim: "employment_entity", findings: [a, b] },
    ]);
    vi.mocked(resolveCompanyFinding).mockResolvedValue(a);
    render(<CompanyResearchPage />);
    await screen.findByText("AAA");
    vi.mocked(listCompanyFindings).mockRejectedValue(new Error("refetch boom"));
    fireEvent.click(screen.getAllByRole("button", { name: "Accept" })[0]);
    expect(await screen.findByText("refetch boom")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("shows a load error separately from the empty state", async () => {
    vi.mocked(listCompanyFindings).mockRejectedValue(new Error("boom"));
    render(<CompanyResearchPage />);
    expect(await screen.findByText("boom")).toBeTruthy();
    expect(screen.queryByText(/No company findings recorded yet/i)).toBeNull();
  });
});
