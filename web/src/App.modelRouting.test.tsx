// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";
import { WizardProvider } from "./wizard/store";
import { getRouting, listConnections } from "./api/client";

vi.mock("./api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/client")>();
  return { ...actual,
    getOnboarding: vi.fn().mockResolvedValue({ providerDone: true, hasProfile: false,
      cvReviewedAt: "2024-01-01", tourSeenAt: "2024-01-01", complete: true }),
    listPendingApprovals: vi.fn().mockResolvedValue([]),
    getSigninQueue: vi.fn().mockResolvedValue({ sites: [] }),
    getRouting: vi.fn().mockResolvedValue({ default: null, agent: null, tasks: {} }),
    listConnections: vi.fn().mockResolvedValue({ encryptionAvailable: true, connections: [] }),
  };
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });
describe("App model routing URL", () => {
  it("opens /model-routing directly and navigates from the sidebar", async () => {
    render(<WizardProvider><MemoryRouter initialEntries={["/model-routing"]}><App /></MemoryRouter></WizardProvider>);
    expect(await screen.findByRole("heading", { name: "Model routing" })).toBeTruthy();
    expect(await screen.findByText("Accounts")).toBeTruthy();
    expect(getRouting).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Model routing" }));
    expect(screen.getByRole("heading", { name: "Model routing" })).toBeTruthy();
    expect(listConnections).toHaveBeenCalled();
  });
});
