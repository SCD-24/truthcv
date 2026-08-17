// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { listConnectionModels, testConnectionProvider, updateRouting } from "../api/client";
import type { ConnectionStatus, ModelInfo, Routing } from "../api/types";
import { DefaultModelSection } from "./DefaultModelSection";

/** Mirrors AccountsSection.test.tsx's boundary choice — mock the API client
 * module directly and render with @testing-library/react + jsdom, scoped to
 * this file via the environment docblock above. */
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

const models: ModelInfo[] = [
  { id: "claude-opus-5", label: "Opus 5" },
  { id: "claude-sonnet-5", label: "Sonnet 5" },
];

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DefaultModelSection", () => {
  it("connection select lists only connected cards", () => {
    const connections = [
      makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true }),
      makeStatus({ provider: "codex", label: "Codex", subscriptionConnected: false, apiKeyConnected: false }),
      makeStatus({ provider: "ollama", label: "Ollama", apiKeyConnected: true }),
    ];
    render(
      <DefaultModelSection connections={connections} routing={makeRouting()} onSaved={vi.fn()} />,
    );

    fireEvent.mouseDown(screen.getByLabelText(/connection/i));
    expect(screen.getByRole("option", { name: "Claude" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Ollama" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Codex" })).toBeNull();
  });

  it("choosing a connection loads its models", async () => {
    // The section auto-loads models for the initially-selected connection
    // (here "claude", first connected) on mount, then again when the user
    // switches to "codex" — so the mock must answer by provider, not by call order.
    vi.mocked(listConnectionModels).mockImplementation(async (provider) =>
      provider === "codex" ? models : [],
    );
    const connections = [
      makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true }),
      makeStatus({ provider: "codex", label: "Codex", apiKeyConnected: true }),
    ];
    render(
      <DefaultModelSection connections={connections} routing={makeRouting()} onSaved={vi.fn()} />,
    );

    fireEvent.mouseDown(screen.getByLabelText(/connection/i));
    fireEvent.click(screen.getByRole("option", { name: "Codex" }));

    await vi.waitFor(() => {
      expect(listConnectionModels).toHaveBeenCalledWith("codex");
    });

    fireEvent.mouseDown(screen.getByLabelText(/^model$/i));
    expect(await screen.findByRole("option", { name: "Sonnet 5" })).toBeTruthy();
  });

  it("Save calls updateRouting with {default: {connection, model}}", async () => {
    vi.mocked(listConnectionModels).mockResolvedValueOnce(models);
    vi.mocked(updateRouting).mockResolvedValueOnce(
      makeRouting({ default: { connection: "claude", model: "claude-opus-5" } }),
    );
    const onSaved = vi.fn();
    const connections = [
      makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true }),
    ];
    render(
      <DefaultModelSection connections={connections} routing={makeRouting()} onSaved={onSaved} />,
    );

    await vi.waitFor(() => {
      expect(listConnectionModels).toHaveBeenCalledWith("claude");
    });
    fireEvent.mouseDown(screen.getByLabelText(/^model$/i));
    fireEvent.click(await screen.findByRole("option", { name: "Opus 5" }));

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await vi.waitFor(() => {
      expect(updateRouting).toHaveBeenCalledWith({
        default: { connection: "claude", model: "claude-opus-5" },
      });
    });
    expect(onSaved).toHaveBeenCalledWith(
      makeRouting({ default: { connection: "claude", model: "claude-opus-5" } }),
    );
  });

  it("Test renders the mocked TestResult.detail", async () => {
    vi.mocked(listConnectionModels).mockResolvedValueOnce(models);
    vi.mocked(testConnectionProvider).mockResolvedValueOnce({ ok: true, detail: "Connected fine." });
    const connections = [
      makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true }),
    ];
    render(
      <DefaultModelSection connections={connections} routing={makeRouting()} onSaved={vi.fn()} />,
    );

    await vi.waitFor(() => {
      expect(listConnectionModels).toHaveBeenCalledWith("claude");
    });

    fireEvent.click(screen.getByRole("button", { name: /test/i }));

    expect(await screen.findByText("Connected fine.")).toBeTruthy();
    expect(testConnectionProvider).toHaveBeenCalledWith("claude", "");
  });
});
