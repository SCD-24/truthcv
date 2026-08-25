// @vitest-environment jsdom
import { afterEach, describe, it, expect, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { deleteScreening, listScreenings, setScreeningRole } from "../api/client";
import type { ScreeningRecord } from "../api/types";
import { ScreeningsPage } from "./ScreeningsPage";

/** Mirrors AgentsPage.profiles.test.tsx's boundary choice — mock the API
 * client module directly and render with @testing-library/react + jsdom. */
vi.mock("../api/client", () => ({
  listScreenings: vi.fn(),
  deleteScreening: vi.fn(),
  setScreeningRole: vi.fn(),
}));

/** Build a ScreeningRecord fixture shaped exactly like the ones the backend
 * emits (screening/model.py's Screening dataclass, serialised camelCase per
 * api/schemas.py). */
function makeScreening(overrides: Partial<ScreeningRecord> = {}): ScreeningRecord {
  return {
    id: "a1b2c3d4e5f6",
    company: "Acme Corp",
    role: "Engineer",
    url: "https://acme.example/careers/123",
    screenedDate: "2024-06-01T12:00:00+00:00",
    verdict: "rejected",
    failingCriterion: "salary",
    reason: "Salary below stated minimum.",
    cooldownExpires: "2024-09-01T12:00:00+00:00",
    source: "agent",
    postingText: "",
    postedDate: "",
    approval: "",
    applyAttempts: 0,
    applyError: "",
    screeningBlocker: "",
    claimedByRun: "",
    claimExpiresAt: "",
    createdAt: "2024-06-01T12:00:00+00:00",
    updatedAt: "2024-06-01T12:00:00+00:00",
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ScreeningsPage", () => {
  it("renders screening rows returned by listScreenings", async () => {
    vi.mocked(listScreenings).mockResolvedValue([
      makeScreening({ id: "s1", company: "Acme Corp", role: "Engineer" }),
      makeScreening({ id: "s2", company: "Globex", role: "Analyst" }),
    ]);

    render(<ScreeningsPage onBack={vi.fn()} />);

    expect(await screen.findByText("Acme Corp")).toBeTruthy();
    expect(screen.getByText("Globex")).toBeTruthy();
    expect(screen.getByText("Engineer")).toBeTruthy();
    expect(screen.getByText("Analyst")).toBeTruthy();
  });

  it("labels an active cooldown (future expiry) differently from an expired one (past expiry)", async () => {
    const future = new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString();
    const past = new Date(Date.now() - 1000 * 60 * 60 * 24 * 30).toISOString();
    vi.mocked(listScreenings).mockResolvedValue([
      makeScreening({ id: "active", company: "Acme Corp", cooldownExpires: future }),
      makeScreening({ id: "expired", company: "Globex", cooldownExpires: past }),
    ]);

    render(<ScreeningsPage onBack={vi.fn()} />);
    await screen.findByText("Acme Corp");

    expect(screen.getByText(`Until ${future}`)).toBeTruthy();
    expect(screen.getByText("Expired")).toBeTruthy();
  });

  it("clicking delete calls deleteScreening with the record's id", async () => {
    vi.mocked(listScreenings).mockResolvedValue([
      makeScreening({ id: "s1", company: "Acme Corp" }),
    ]);
    vi.mocked(deleteScreening).mockResolvedValue(undefined);

    render(<ScreeningsPage onBack={vi.fn()} />);
    await screen.findByText("Acme Corp");

    fireEvent.click(screen.getByRole("button", { name: "Delete screening record for Acme Corp" }));

    await vi.waitFor(() => {
      expect(deleteScreening).toHaveBeenCalledWith("s1");
    });
  });

  it("clicking the role cell opens an editor seeded with the current role", async () => {
    vi.mocked(listScreenings).mockResolvedValue([
      makeScreening({ id: "s1", company: "Acme Corp", role: "Engineer" }),
    ]);

    render(<ScreeningsPage onBack={vi.fn()} />);
    await screen.findByText("Acme Corp");

    fireEvent.click(screen.getByText("Engineer"));

    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("Engineer");
  });

  it("committing shows the server's (normalized) response, not the typed string", async () => {
    vi.mocked(listScreenings).mockResolvedValue([
      makeScreening({ id: "s1", company: "Acme Corp", role: "Engineer" }),
    ]);
    vi.mocked(setScreeningRole).mockResolvedValue(
      makeScreening({ id: "s1", company: "Acme Corp", role: "Senior Backend Engineer" }),
    );

    render(<ScreeningsPage onBack={vi.fn()} />);
    await screen.findByText("Acme Corp");

    fireEvent.click(screen.getByText("Engineer"));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "senior  backend engineer" },
    });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });

    await vi.waitFor(() => {
      expect(setScreeningRole).toHaveBeenCalledWith("s1", "senior  backend engineer");
    });
    expect(await screen.findByText("Senior Backend Engineer")).toBeTruthy();
  });

  it("Escape cancels without calling the client and restores the original value", async () => {
    vi.mocked(listScreenings).mockResolvedValue([
      makeScreening({ id: "s1", company: "Acme Corp", role: "Engineer" }),
    ]);

    render(<ScreeningsPage onBack={vi.fn()} />);
    await screen.findByText("Acme Corp");

    fireEvent.click(screen.getByText("Engineer"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "garbage" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Escape" });

    expect(setScreeningRole).not.toHaveBeenCalled();
    expect(await screen.findByText("Engineer")).toBeTruthy();
  });

  it("a rejected commit shows the server's error and leaves the displayed role unchanged", async () => {
    vi.mocked(listScreenings).mockResolvedValue([
      makeScreening({ id: "s1", company: "Acme Corp", role: "Engineer" }),
    ]);
    vi.mocked(setScreeningRole).mockRejectedValue(new Error("Not a valid job title."));

    render(<ScreeningsPage onBack={vi.fn()} />);
    await screen.findByText("Acme Corp");

    fireEvent.click(screen.getByText("Engineer"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Apply now" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });

    expect(await screen.findByText("Not a valid job title.")).toBeTruthy();
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("Apply now");
  });

  it("an empty role renders the placeholder and stays clickable", async () => {
    vi.mocked(listScreenings).mockResolvedValue([
      makeScreening({ id: "s1", company: "Acme Corp", role: "" }),
    ]);

    render(<ScreeningsPage onBack={vi.fn()} />);
    await screen.findByText("Acme Corp");

    fireEvent.click(screen.getByText("—"));

    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("");
  });
});
