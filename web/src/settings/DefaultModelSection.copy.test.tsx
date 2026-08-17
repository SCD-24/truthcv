// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { listConnectionModels, updateRouting } from "../api/client";
import type { ConnectionStatus, ModelInfo, Routing } from "../api/types";
import { DefaultModelSection } from "./DefaultModelSection";

/** Separate from DefaultModelSection.test.tsx (kept untouched by the
 * ModelRoutePicker extraction) — covers the wrapper's `savedLabel` override,
 * which restores the section's original "Default model saved." copy on top
 * of the shared picker's generic default. Mirrors that file's mocking style. */
vi.mock("../api/client", () => ({
  listConnectionModels: vi.fn(),
  testConnectionProvider: vi.fn(),
  updateRouting: vi.fn(),
}));

function makeStatus(overrides: Partial<ConnectionStatus> = {}): ConnectionStatus {
  return {
    provider: "claude",
    label: "Claude",
    modes: ["subscription"],
    subscriptionConnected: false,
    apiKeyConnected: false,
    authMode: "subscription",
    expiresAt: null,
    connectedAt: null,
    ...overrides,
  };
}

function makeRouting(overrides: Partial<Routing> = {}): Routing {
  return {
    tasks: {},
    agent: null,
    default: null,
    ...overrides,
  };
}

const models: ModelInfo[] = [{ id: "claude-opus-5", label: "Opus 5" }];

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DefaultModelSection saved copy", () => {
  it("shows 'Default model saved.' after a successful save", async () => {
    vi.mocked(listConnectionModels).mockResolvedValueOnce(models);
    vi.mocked(updateRouting).mockResolvedValueOnce(
      makeRouting({ default: { connection: "claude", model: "claude-opus-5" } }),
    );
    const connections = [
      makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true }),
    ];
    render(
      <DefaultModelSection connections={connections} routing={makeRouting()} onSaved={vi.fn()} />,
    );

    await vi.waitFor(() => {
      expect(listConnectionModels).toHaveBeenCalledWith("claude");
    });

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText("Default model saved.")).toBeTruthy();
  });
});
