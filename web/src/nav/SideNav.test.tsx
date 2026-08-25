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
  it("renders all nine buttons", () => {
    render(<SideNav {...props} />);
    const labels = [
      "Upload CV",
      "Manual",
      "Applications",
      "Analytics",
      "Agents",
      "Screenings",
      "Company Research",
      "Approvals",
      "Settings",
    ];
    for (const label of labels) {
      expect(screen.getByRole("button", { name: new RegExp(label, "i") })).toBeTruthy();
    }
  });

  it("shows the pending approvals count", () => {
    render(<SideNav {...props} pendingApprovals={3} />);
    const button = screen.getByRole("button", { name: /approvals/i });
    expect(within(button).getByText("3")).toBeTruthy();
  });

  it("shows the number of sites waiting on a sign-in", () => {
    render(<SideNav {...props} signinSites={2} />);
    const button = screen.getByRole("button", { name: /^agents$/i });
    expect(within(button).getByText("2")).toBeTruthy();
  });

  it("shows nothing on Agents when no site is waiting", () => {
    render(<SideNav {...props} />);
    const button = screen.getByRole("button", { name: /^agents$/i });
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
