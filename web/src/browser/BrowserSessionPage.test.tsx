// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { BrowserSessionPage } from "./BrowserSessionPage";

// `vi.mock` factories are hoisted above the rest of the module, so the mock
// class and the holder that captures its latest instance must be created
// through `vi.hoisted` rather than as ordinary top-level declarations.
const { MockRfb, rfbHolder } = vi.hoisted(() => {
  const rfbHolder: { current: InstanceType<typeof MockRfbClass> | null } = { current: null };
  class MockRfbClass {
    private listeners: Record<string, Array<(e?: unknown) => void>> = {};
    constructor() {
      rfbHolder.current = this;
    }
    addEventListener(type: string, cb: (e?: unknown) => void) {
      (this.listeners[type] ||= []).push(cb);
    }
    // Fires registered listeners synchronously, like the real RFB does when
    // its socket closes — needed so the Reload test below can actually
    // exercise the disconnect handler's reload-vs-real-close guard, not just
    // call a no-op.
    disconnect() {
      this.listeners["disconnect"]?.forEach((cb) => cb());
    }
    dispatch(type: string, detail?: unknown) {
      this.listeners[type]?.forEach((cb) => cb(detail !== undefined ? { detail } : undefined));
    }
  }
  return { MockRfb: MockRfbClass, rfbHolder };
});

vi.mock("@novnc/novnc/lib/rfb", () => ({
  default: MockRfb,
}));

// Mirrors what the real RFB does: a failed handshake fires `securityfailure`
// immediately followed by `disconnect` on the same socket. The disconnect
// handler must not be allowed to overwrite the securityfailure state.
function triggerSecurityFailureThenDisconnect(reason: string) {
  rfbHolder.current?.dispatch("securityfailure", { reason });
  rfbHolder.current?.dispatch("disconnect");
}

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

  it("Reload re-establishes the viewport instead of ending the session", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true,
      status: 200,
      json: async () => ({ open: true, url: "https://example.com/login", startedAt: "x", evictDeadline: null }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("example.com")).toBeTruthy();
    });

    const reload = screen.getByRole("button", { name: /reload/i });
    fireEvent.click(reload);

    // Give any state update from the disconnect handler a chance to land,
    // then confirm it's still the live view, not "closed" — Reload tore
    // down and rebuilt only the viewer socket.
    await waitFor(() => {
      expect(screen.getByText("example.com")).toBeTruthy();
    });
    expect(screen.queryByText(/if it worked, the next run will get through/i)).toBeNull();
    // And it never told the session server to close the session.
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "DELETE")).toBe(
      false,
    );
  });

  it("keeps showing the securityfailure reason after the disconnect that follows it", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("example.com")).toBeTruthy();
    });

    triggerSecurityFailureThenDisconnect("bad handshake");

    await waitFor(() => {
      expect(screen.getByText(/bad handshake/i)).toBeTruthy();
    });
    expect(screen.queryByText(/if it worked, the next run will get through/i)).toBeNull();
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
    expect(screen.getByText(/other\.example\.com/)).toBeTruthy();
  });

  it("attaches to the session when the refusal names the URL this page wants", async () => {
    // The operator left this page without pressing Done and came back. The
    // POST is refused with the SAME url — which is not a refusal to show
    // them anything, it is the session they asked for. Before this, the page
    // showed a refusal whose only button navigated to the page it was
    // already on, stranding them until a run evicted the session.
    const url = "https://example.com/login";
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        return {
          ok: false,
          status: 409,
          json: async () => ({ detail: { reason: "session_open", url } }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ open: true, url, startedAt: "x", evictDeadline: null }),
      };
    }));
    renderPage(url);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /done/i })).toBeTruthy();
    });
    expect(screen.queryByText(/already open/i)).toBeNull();
  });

  it("closes the session that is in the way and starts this one", async () => {
    const url = "https://example.com/login";
    let sessionOpen = true;
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "DELETE") {
        sessionOpen = false;
        return { ok: true, status: 200, json: async () => ({ closed: true }) };
      }
      if (init?.method === "POST") {
        if (sessionOpen) {
          return {
            ok: false,
            status: 409,
            json: async () => ({
              detail: { reason: "session_open", url: "https://other.example.com/login" },
            }),
          };
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({ open: true, url, startedAt: "x", evictDeadline: null }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ open: sessionOpen, url, startedAt: "x", evictDeadline: null }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage(url);

    const closeIt = await screen.findByRole("button", { name: /close it and start here/i });
    fireEvent.click(closeIt);

    // Ends up live on THIS url, having actually closed the other session.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /done/i })).toBeTruthy();
    });
    expect(
      fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "DELETE"),
    ).toBe(true);
  });

  it("gives a 503 agent_unreachable its own words", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ detail: { reason: "agent_unreachable" } }),
    })));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/agent could not be reached/i)).toBeTruthy();
    });
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
