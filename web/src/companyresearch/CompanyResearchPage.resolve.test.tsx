// @vitest-environment jsdom
/** Company Research page: resolving a contradiction keeps the cards busy until
 * the refetch lands. Mocks the API client as CompanyResearchPage.test.tsx does. */
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { listCompanyGroupsPage, listContradictions, resolveCompanyFinding } from "../api/client";
import type { CompanyFinding, CompanyGroupPage } from "../api/types";
import { CompanyResearchPage } from "./CompanyResearchPage";

vi.mock("../api/client", () => ({
  listCompanyGroupsPage: vi.fn(),
  listContradictions: vi.fn(),
  createCompanyFinding: vi.fn(),
  resolveCompanyFinding: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

/** A finding shaped like the backend's camelCase serialisation. */
function makeFinding(id: string, value: string, sourceClass: CompanyFinding["sourceClass"]): CompanyFinding {
  return {
    id,
    company: "Acme Corp",
    companyKey: "acme corp",
    claim: "employment_entity",
    claimLabel: "",
    supersedes: "",
    value,
    sourceUrl: "https://acme.example/about",
    sourceClass,
    asOf: "2024-01-01",
    observedAt: "2024-06-01T12:00:00+00:00",
    recordedBy: "operator",
    note: "",
    contradicts: [],
    resolution: "",
    resolvedAt: "",
    resolutionNote: "",
  };
}

function makePage(findings: CompanyFinding[]): CompanyGroupPage {
  const group = { companyKey: "acme corp", company: "Acme Corp", findings, needsReview: true };
  return { items: [group], total: 1, limit: 50, offset: 0, companies: ["Acme Corp"] };
}

const rejectButtons = () => screen.getAllByRole("button", { name: "Reject" }) as HTMLButtonElement[];

it("keeps Accept/Reject disabled until the refetch after a resolve lands", async () => {
  const a = makeFinding("a", "AAA", "audited_accounts");
  const b = makeFinding("b", "BBB", "company_statement");
  vi.mocked(listCompanyGroupsPage).mockResolvedValueOnce(makePage([a, b]));
  vi.mocked(listContradictions).mockResolvedValue([{ claim: "employment_entity", findings: [a, b] }]);
  vi.mocked(resolveCompanyFinding).mockResolvedValue(a);
  let land: (page: CompanyGroupPage) => void = () => {};
  vi.mocked(listCompanyGroupsPage).mockReturnValueOnce(new Promise((resolve) => (land = resolve)));
  render(<CompanyResearchPage />);
  await screen.findByText("AAA");

  fireEvent.click(rejectButtons()[0]);
  await waitFor(() => expect(listCompanyGroupsPage).toHaveBeenCalledTimes(2));
  expect(resolveCompanyFinding).toHaveBeenCalledWith("a", "rejected");
  expect(rejectButtons().every((btn) => btn.disabled)).toBe(true);

  await act(async () => land(makePage([a, b])));
  await waitFor(() => expect(rejectButtons().every((btn) => !btn.disabled)).toBe(true));
});
