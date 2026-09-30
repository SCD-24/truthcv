// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { CompanyFinding } from "../api/types";
import { FindingDialog } from "./FindingDialog";

afterEach(() => {
  cleanup();
});

function makeFinding(overrides: Partial<CompanyFinding> = {}): CompanyFinding {
  return {
    id: "f1",
    company: "Acme GmbH",
    companyKey: "acme",
    claim: "employment_entity",
    claimLabel: "",
    supersedes: "",
    value: "Acme GmbH",
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

const field = (name: string) => screen.getByLabelText(new RegExp(`^${name}`));

describe("FindingDialog", () => {
  it("submits a new finding", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(<FindingDialog companies={["Acme"]} onClose={onClose} onSubmit={onSubmit} />);

    fireEvent.change(field("Company"), { target: { value: "Globex" } });
    fireEvent.change(field("Value"), { target: { value: "Globex AG" } });
    fireEvent.change(field("Source URL"), { target: { value: "https://globex.example/ir" } });
    fireEvent.click(screen.getByRole("button", { name: "Add finding" }));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          company: "Globex",
          claim: "employment_entity",
          value: "Globex AG",
          sourceUrl: "https://globex.example/ir",
          supersedes: undefined,
        }),
      ),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("edit mode is prefilled, locked, and submits supersedes", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <FindingDialog
        finding={makeFinding()}
        companies={[]}
        onClose={() => {}}
        onSubmit={onSubmit}
      />,
    );

    expect(screen.getByText("Correct finding")).toBeTruthy();
    expect((field("Company") as HTMLInputElement).disabled).toBe(true);
    expect((field("Claim type") as HTMLSelectElement).disabled).toBe(true);
    expect((field("Value") as HTMLInputElement).value).toBe("Acme GmbH");

    fireEvent.change(field("Value"), { target: { value: "Acme SE" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ supersedes: "f1", company: "Acme GmbH", value: "Acme SE" }),
      ),
    );
  });

  it("requires a source URL containing ://", async () => {
    const onSubmit = vi.fn();
    render(<FindingDialog companies={[]} onClose={() => {}} onSubmit={onSubmit} />);
    fireEvent.change(field("Company"), { target: { value: "Globex" } });
    fireEvent.change(field("Value"), { target: { value: "x" } });

    fireEvent.click(screen.getByRole("button", { name: "Add finding" }));
    expect(await screen.findByText(/every finding must cite/i, { selector: "p" })).toBeTruthy();

    fireEvent.change(field("Source URL"), { target: { value: "example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Add finding" }));
    expect(await screen.findByText(/full link/i)).toBeTruthy();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("requires a label for 'other' and sends it", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<FindingDialog companies={[]} onClose={() => {}} onSubmit={onSubmit} />);
    expect(screen.queryByLabelText(/^Claim label/)).toBeNull();

    fireEvent.change(field("Claim type"), { target: { value: "other" } });
    fireEvent.change(field("Company"), { target: { value: "Globex" } });
    fireEvent.change(field("Value"), { target: { value: "300" } });
    fireEvent.change(field("Source URL"), { target: { value: "https://g.example/x" } });

    fireEvent.click(screen.getByRole("button", { name: "Add finding" }));
    expect(await screen.findByText(/label is required/i)).toBeTruthy();
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.change(field("Claim label"), { target: { value: " Headcount " } });
    fireEvent.click(screen.getByRole("button", { name: "Add finding" }));
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ claim: "other", claimLabel: "Headcount" }),
      ),
    );
  });

  it("shows a server error inline and stays open", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("already superseded"));
    const onClose = vi.fn();
    render(<FindingDialog companies={[]} onClose={onClose} onSubmit={onSubmit} />);
    fireEvent.change(field("Company"), { target: { value: "Globex" } });
    fireEvent.change(field("Value"), { target: { value: "x" } });
    fireEvent.change(field("Source URL"), { target: { value: "https://g.example/x" } });
    fireEvent.click(screen.getByRole("button", { name: "Add finding" }));

    expect(await screen.findByText("already superseded")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });
});
