// @vitest-environment jsdom
/** The rail's Approvals entry and its pending badge. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { StepRail } from "./StepRail";

afterEach(cleanup);

const props = {
  current: "upload" as const,
  reached: "upload" as const,
  onNavigate: () => {},
  onOpenSettings: () => {},
  onOpenApplications: () => {},
  onOpenAnalytics: () => {},
  onOpenAgents: () => {},
  onOpenScreenings: () => {},
  onOpenApprovals: () => {},
};

describe("StepRail approvals entry", () => {
  it("renders an Approvals button", () => {
    render(<StepRail {...props} />);
    expect(screen.getByRole("button", { name: /approvals/i })).toBeTruthy();
  });

  it("shows the pending count when there is one", () => {
    // Scoped to the button: the rail's step markers are numbered too.
    render(<StepRail {...props} pendingApprovals={3} />);
    const button = screen.getByRole("button", { name: /approvals/i });
    expect(within(button).getByText("3")).toBeTruthy();
  });

  it("shows no badge at zero", () => {
    render(<StepRail {...props} pendingApprovals={0} />);
    const button = screen.getByRole("button", { name: /approvals/i });
    expect(within(button).queryByText("0")).toBeNull();
  });

  it("calls onOpenApprovals when clicked", () => {
    const onOpenApprovals = vi.fn();
    render(<StepRail {...props} onOpenApprovals={onOpenApprovals} />);
    fireEvent.click(screen.getByRole("button", { name: /approvals/i }));
    expect(onOpenApprovals).toHaveBeenCalled();
  });
});
