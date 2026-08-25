// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { BrowserSessionPage } from "./BrowserSessionPage";

vi.mock("@novnc/novnc/lib/rfb", () => ({
  default: class {
    addEventListener() {}
    disconnect() {}
  },
}));

function renderPage(url = "https://example.com/login") {
  return render(
    <MemoryRouter initialEntries={[`/browser-session?url=${encodeURIComponent(url)}`]}>
      <BrowserSessionPage />
    </MemoryRouter>
  );
}

describe("BrowserSessionPage", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ open: true, url: "https://example.com/login", startedAt: "x", evictDeadline: null }),
    })));
  });

  it("shows a starting state before the session is open", () => {
    renderPage();
    expect(screen.getByText(/starting/i)).toBeTruthy();
  });

  it("shows the site host once the session is live", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("example.com")).toBeTruthy();
    });
  });

  it("explains that the agent is busy when the session is refused with 409", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false,
      status: 409,
      json: async () => ({ detail: "Session refused" }),
    })));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/agent is applying right now/i)).toBeTruthy();
    });
  });

  it("counts down when a run has asked for the browser back", async () => {
    const deadline = new Date(Date.now() + 165000).toISOString();
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ open: true, url: "https://example.com/login", startedAt: "x", evictDeadline: deadline }),
    })));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/the agent needs the browser in 2:4/i)).toBeTruthy();
    });
  });

  it("does not claim the sign-in succeeded when closed", async () => {
    renderPage();
    const done = await screen.findByRole("button", { name: /done/i });
    done.click();
    await waitFor(() => {
      expect(screen.getByText(/if it worked, the next run will get through/i)).toBeTruthy();
    });
    expect(screen.queryByText(/signed in/i)).toBeNull();
  });

  it("reports when the browser service is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ detail: "Browser service unreachable" }),
    })));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/browser is unavailable/i)).toBeTruthy();
    });
  });

  it("offers to return to the already-open session on a session_open refusal", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false,
      status: 409,
      json: async () => ({ detail: { reason: "session_open", url: "https://other.example.com/login" } }),
    })));
    renderPage();
    const goTo = await screen.findByRole("button", { name: /go to the open session/i });
    expect(goTo).toBeTruthy();
  });

  it("distinguishes a launch failure from the agent being busy", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false,
      status: 409,
      json: async () => ({ detail: { reason: "launch_failed" } }),
    })));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/browser could not be started/i)).toBeTruthy();
    });
    expect(screen.queryByText(/agent is applying right now/i)).toBeNull();
  });
});
