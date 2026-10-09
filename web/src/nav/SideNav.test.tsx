// @vitest-environment jsdom
/** The sidebar's flat destination list. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { SideNav } from "./SideNav";

afterEach(cleanup);

const props = {
  pathname: "/analytics",
  onNavigate: () => {},
  onOpenSettings: () => {},
};

describe("SideNav", () => {
  it("renders the model routing destination", () => {
    render(<SideNav {...props} />);
    const labels = [
      "Upload CV",
      "Truth file",
      "Manual",
      "Writing Style",
      "Email responses",
      "Job boards",
      "Applications",
      "Analytics",
      "Agents",
      "Model routing",
      "Screenings",
      "Company Research",
      "Approvals",
      "Settings",
    ];
    for (const label of labels) {
      expect(screen.getByRole("button", { name: new RegExp(label, "i") })).toBeTruthy();
    }
  });

  it("groups destinations under ordered headings", () => {
    render(<SideNav {...props} />);
    const expected: Record<string, string[]> = {
      "Your profile": ["Upload CV", "Truth file", "Manual", "Writing Style"],
      "Find jobs": ["Job boards", "Screenings", "Company Research"],
      Applications: ["Approvals", "Applications", "Email responses", "Analytics"],
      Automation: ["Agents", "Model routing"],
    };
    // Group labels are deliberately not headings, so they never collide with
    // the page's own heading outline; each one names its region instead.
    const order = screen
      .getAllByRole("region")
      .map((r) => document.getElementById(r.getAttribute("aria-labelledby") ?? "")?.textContent);
    expect(order).toEqual(Object.keys(expected));
    expect(screen.queryAllByRole("heading")).toHaveLength(0);
    for (const [name, labels] of Object.entries(expected)) {
      const region = screen.getByRole("region", { name });
      const names = within(region)
        .getAllByRole("button")
        .map((b) => b.textContent);
      expect(names).toEqual(labels);
    }
  });

  it("keeps Settings as the last button in the nav", () => {
    render(<SideNav {...props} />);
    const buttons = within(screen.getByRole("navigation")).getAllByRole("button");
    expect(buttons[buttons.length - 1].textContent).toBe("Settings");
  });

  it("shows the pending approvals count", () => {
    render(<SideNav {...props} pendingApprovals={3} />);
    const button = screen.getByRole("button", { name: /approvals/i });
    expect(within(button).getByText("3")).toBeTruthy();
  });

  it("shows the number of sites waiting on a sign-in", () => {
    render(<SideNav {...props} signinSites={2} />);
    const button = screen.getByRole("button", { name: /^job boards$/i });
    expect(within(button).getByText("2")).toBeTruthy();
  });

  it("shows nothing on Job boards when no site is waiting", () => {
    render(<SideNav {...props} />);
    const button = screen.getByRole("button", { name: /^job boards$/i });
    // A count of zero is not news, and an empty badge on a permanent nav item
    // reads as an alert that never clears.
    expect(within(button).queryByText("0")).toBeNull();
  });

  it("has no numbered step markers", () => {
    render(<SideNav {...props} />);
    expect(document.querySelector(".rail__marker")).toBeNull();
    expect(document.querySelector(".rail__steps")).toBeNull();
  });

  it("calls onNavigate with /manual when Manual is clicked", () => {
    const onNavigate = vi.fn();
    render(<SideNav {...props} onNavigate={onNavigate} />);
    fireEvent.click(screen.getByRole("button", { name: /manual/i }));
    expect(onNavigate).toHaveBeenCalledWith("/manual");
  });
});
