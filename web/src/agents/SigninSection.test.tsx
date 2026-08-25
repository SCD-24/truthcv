// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { SigninSection } from "./SigninSection";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderSection() {
  return render(
    <MemoryRouter>
      <SigninSection sources={["linkedin", "greenhouse"]} />
    </MemoryRouter>
  );
}

describe("SigninSection", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    mockNavigate.mockReset();
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ sites: [] }),
    })));
  });

  it("says nothing needs attention when the queue is empty", async () => {
    renderSection();
    await waitFor(() => {
      expect(screen.getByText(/no sites are waiting/i)).toBeTruthy();
    });
  });

  it("lists a blocked site with how many postings are waiting", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        sites: [{
          host: "acme.wd3.myworkdayjobs.com",
          signinUrl: "https://acme.wd3.myworkdayjobs.com/login",
          waiting: 4,
          lastBlockedAt: "2026-08-25T15:02:00Z",
          companies: ["Acme"],
        }],
      }),
    })));
    renderSection();
    await waitFor(() => {
      expect(screen.getByText(/acme\.wd3\.myworkdayjobs\.com/, { selector: "p" })).toBeTruthy();
    });
    expect(screen.getByText(/4 postings waiting/i)).toBeTruthy();
  });

  it("lists the configured job boards so they can be signed in to ahead of time", async () => {
    renderSection();
    await waitFor(() => {
      expect(screen.getByText(/linkedin/i, { selector: "p" })).toBeTruthy();
    });
  });

  it("shows no signed-in status for configured boards", async () => {
    // The agent's experience is the only source of truth, so claiming a board
    // is signed in would be an assertion nothing checks.
    renderSection();
    await waitFor(() => {
      expect(screen.getByText(/linkedin/i, { selector: "p" })).toBeTruthy();
    });
    expect(screen.queryByText(/signed in/i)).toBeNull();
  });

  it("navigates to the session page with the url when Sign in is clicked", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        sites: [{
          host: "acme.wd3.myworkdayjobs.com",
          signinUrl: "https://acme.wd3.myworkdayjobs.com/login",
          waiting: 1,
          lastBlockedAt: "2026-08-25T15:02:00Z",
          companies: ["Acme"],
        }],
      }),
    })));
    renderSection();
    const button = await screen.findByRole("button", {
      name: /sign in to acme\.wd3\.myworkdayjobs\.com/i,
    });
    button.click();
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        expect.stringContaining("/browser-session")
      );
    });
  });
});
