// @vitest-environment jsdom
import { afterEach, describe, it, expect, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { deleteScreening, listScreeningLedgerPage, setScreeningRole } from "../api/client";
import type { ScreeningLedgerItem, ScreeningLedgerPage } from "../api/types";
import { ScreeningsPage } from "./ScreeningsPage";

/** Mirrors AgentsPage.profiles.test.tsx's boundary choice — mock the API
 * client module directly and render with @testing-library/react + jsdom. */
vi.mock("../api/client", () => ({
  listScreeningLedgerPage: vi.fn(),
  deleteScreening: vi.fn(),
  setScreeningRole: vi.fn(),
}));

/** Build a ScreeningLedgerItem fixture shaped exactly like the ones the backend
 * emits (truthcv/domain/screening/model.py's Screening dataclass, serialised camelCase per
 * truthcv/adapters/http/schemas/screenings.py's ScreeningLedgerItemModel — no postingText). */
function makeScreening(overrides: Partial<ScreeningLedgerItem> = {}): ScreeningLedgerItem {
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
    postedDate: "",
    approval: "",
    applyAttempts: 0,
    applyError: "",
    screeningBlocker: "",
    profile: "",
    remoteArrangement: "",
    languageRequirement: "",
    claimedByRun: "",
    claimExpiresAt: "",
    createdAt: "2024-06-01T12:00:00+00:00",
    updatedAt: "2024-06-01T12:00:00+00:00",
    ...overrides,
  };
}

/** One GET /api/screenings/ledger response (ScreeningLedgerResponse). */
function makePage(
  items: ScreeningLedgerItem[],
  overrides: Partial<ScreeningLedgerPage> = {},
): ScreeningLedgerPage {
  return {
    items,
    total: items.length,
    limit: 50,
    offset: 0,
    lastActivity: "2024-06-01T12:00:00+00:00",
    ...overrides,
  };
}

/** Resolve every ledger fetch with `items`. */
function mockLedger(items: ScreeningLedgerItem[]) {
  vi.mocked(listScreeningLedgerPage).mockResolvedValue(makePage(items));
}

/** The options of the most recent ledger fetch. */
function lastLedgerCall() {
  const calls = vi.mocked(listScreeningLedgerPage).mock.calls;
  return calls[calls.length - 1]?.[0];
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ScreeningsPage", () => {
  it("renders screening rows returned by listScreeningLedgerPage", async () => {
    mockLedger([
      makeScreening({ id: "s1", company: "Acme Corp", role: "Engineer" }),
      makeScreening({ id: "s2", company: "Globex", role: "Analyst" }),
    ]);

    render(<ScreeningsPage />);

    expect(await screen.findByText("Acme Corp")).toBeTruthy();
    expect(screen.getByText("Globex")).toBeTruthy();
    expect(screen.getByText("Engineer")).toBeTruthy();
    expect(screen.getByText("Analyst")).toBeTruthy();
  });

  it("labels an active cooldown (future expiry) differently from an expired one (past expiry)", async () => {
    const future = new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString();
    const past = new Date(Date.now() - 1000 * 60 * 60 * 24 * 30).toISOString();
    mockLedger([
      makeScreening({ id: "active", company: "Acme Corp", cooldownExpires: future }),
      makeScreening({ id: "expired", company: "Globex", cooldownExpires: past }),
    ]);

    render(<ScreeningsPage />);
    await screen.findByText("Acme Corp");

    expect(screen.getByText(`Until ${future}`)).toBeTruthy();
    expect(screen.getByText("Expired")).toBeTruthy();
  });

  it("clicking delete calls deleteScreening with the record's id", async () => {
    mockLedger([
      makeScreening({ id: "s1", company: "Acme Corp" }),
    ]);
    vi.mocked(deleteScreening).mockResolvedValue(undefined);

    render(<ScreeningsPage />);
    await screen.findByText("Acme Corp");

    fireEvent.click(screen.getByRole("button", { name: "Delete screening record for Acme Corp" }));

    await vi.waitFor(() => {
      expect(deleteScreening).toHaveBeenCalledWith("s1");
    });
  });

  it("clicking the role cell opens an editor seeded with the current role", async () => {
    mockLedger([
      makeScreening({ id: "s1", company: "Acme Corp", role: "Engineer" }),
    ]);

    render(<ScreeningsPage />);
    await screen.findByText("Acme Corp");

    fireEvent.click(screen.getByText("Engineer"));

    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("Engineer");
  });

  it("committing shows the server's (normalized) response, not the typed string", async () => {
    mockLedger([
      makeScreening({ id: "s1", company: "Acme Corp", role: "Engineer" }),
    ]);
    vi.mocked(setScreeningRole).mockResolvedValue(
      // PATCH returns the full ScreeningModel, posting text included.
      { ...makeScreening({ id: "s1", company: "Acme Corp", role: "Senior Backend Engineer" }), postingText: "" },
    );

    render(<ScreeningsPage />);
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
    mockLedger([
      makeScreening({ id: "s1", company: "Acme Corp", role: "Engineer" }),
    ]);

    render(<ScreeningsPage />);
    await screen.findByText("Acme Corp");

    fireEvent.click(screen.getByText("Engineer"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "garbage" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Escape" });

    expect(setScreeningRole).not.toHaveBeenCalled();
    expect(await screen.findByText("Engineer")).toBeTruthy();
  });

  it("a rejected commit shows the server's error and leaves the displayed role unchanged", async () => {
    mockLedger([
      makeScreening({ id: "s1", company: "Acme Corp", role: "Engineer" }),
    ]);
    vi.mocked(setScreeningRole).mockRejectedValue(new Error("Not a valid job title."));

    render(<ScreeningsPage />);
    await screen.findByText("Acme Corp");

    fireEvent.click(screen.getByText("Engineer"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Apply now" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });

    expect(await screen.findByText("Not a valid job title.")).toBeTruthy();
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("Apply now");
  });

  it("an empty role renders the placeholder and stays clickable", async () => {
    mockLedger([
      makeScreening({ id: "s1", company: "Acme Corp", role: "" }),
    ]);

    render(<ScreeningsPage />);
    await screen.findByText("Acme Corp");

    fireEvent.click(screen.getByText("—"));

    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("");
  });

  it("does not render a back button", async () => {
    mockLedger([
      makeScreening({ id: "s1", company: "Acme Corp" }),
    ]);

    render(<ScreeningsPage />);
    await screen.findByText("Acme Corp");

    expect(screen.queryByRole("button", { name: /back/i })).toBeNull();
  });

  it("first fetch asks for page 1 of 50 and shows the server's lastActivity", async () => {
    vi.mocked(listScreeningLedgerPage).mockResolvedValue(
      makePage([makeScreening({ id: "s1" })], { lastActivity: "2024-07-15T12:00:00+00:00" }),
    );

    render(<ScreeningsPage />);
    await screen.findByText("Acme Corp");

    expect(listScreeningLedgerPage).toHaveBeenCalledWith({ limit: 50, offset: 0, blockedOnly: false });
    const expected = new Date("2024-07-15T12:00:00+00:00").toLocaleDateString();
    expect(screen.getByText(`Last recorded activity: ${expected}`)).toBeTruthy();
  });

  it("the next page fetches offset 50", async () => {
    vi.mocked(listScreeningLedgerPage).mockResolvedValue(
      makePage([makeScreening({ id: "s1" })], { total: 120 }),
    );

    render(<ScreeningsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Go to next page" }));

    await waitFor(() => expect(lastLedgerCall()).toEqual({ limit: 50, offset: 50, blockedOnly: false }));
  });

  it("the couldn't-read checkbox sends blockedOnly and returns to page 1", async () => {
    vi.mocked(listScreeningLedgerPage).mockResolvedValue(
      makePage([makeScreening({ id: "s1" })], { total: 120 }),
    );

    render(<ScreeningsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Go to next page" }));
    await waitFor(() => expect(lastLedgerCall()?.offset).toBe(50));
    fireEvent.click(screen.getByRole("checkbox", { name: "Show only postings the agent couldn't read" }));

    await waitFor(() => expect(lastLedgerCall()).toEqual({ limit: 50, offset: 0, blockedOnly: true }));
  });

  it("deleting the only row on page 2 refetches it, then steps back to page 1", async () => {
    let total = 51;
    vi.mocked(listScreeningLedgerPage).mockImplementation(async ({ offset = 0 }) =>
      offset === 50 && total === 51
        ? makePage([makeScreening({ id: "last", company: "Last Co" })], { total, offset })
        : makePage([makeScreening({ id: "first", company: "First Co" })], { total, offset }),
    );
    vi.mocked(deleteScreening).mockImplementation(async () => {
      total = 50;
    });

    render(<ScreeningsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Go to next page" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete screening record for Last Co" }));

    expect(await screen.findByText("First Co")).toBeTruthy();
    const offsets = vi.mocked(listScreeningLedgerPage).mock.calls.map(([o]) => o.offset);
    expect(offsets).toEqual([0, 50, 50, 0]);
  });

  it("ignores a superseded fetch that resolves after a newer one", async () => {
    let resolveStale: (page: ScreeningLedgerPage) => void = () => {};
    vi.mocked(listScreeningLedgerPage)
      .mockResolvedValueOnce(makePage([makeScreening({ id: "s1" })], { total: 120 }))
      .mockReturnValueOnce(new Promise((resolve) => (resolveStale = resolve)))
      .mockResolvedValueOnce(makePage([makeScreening({ id: "b1", company: "Fresh Co" })]));

    render(<ScreeningsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Go to next page" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Show only postings the agent couldn't read" }));
    await screen.findByText("Fresh Co");
    await act(async () =>
      resolveStale(makePage([makeScreening({ id: "x1", company: "Stale Co" })], { total: 120, offset: 50 })),
    );

    expect(listScreeningLedgerPage).toHaveBeenCalledTimes(3);
    expect(screen.queryByText("Stale Co")).toBeNull();
    expect(screen.getByText("Fresh Co")).toBeTruthy();
  });
});
