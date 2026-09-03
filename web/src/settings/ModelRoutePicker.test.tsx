// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { listConnectionModels, testConnectionProvider } from "../api/client";
import type { ConnectionStatus, ModelInfo } from "../api/types";
import { ModelRoutePicker } from "./ModelRoutePicker";

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

const models: ModelInfo[] = [
  { id: "claude-opus-5", label: "Opus 5" },
  { id: "claude-sonnet-5", label: "Sonnet 5" },
];

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ModelRoutePicker", () => {
  it("filterCards narrows the connection select to the named cards only", () => {
    const connections = [
      makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true }),
      makeStatus({ provider: "codex", label: "Codex", apiKeyConnected: true }),
      makeStatus({ provider: "ollama", label: "Ollama", apiKeyConnected: true }),
    ];
    render(
      <ModelRoutePicker
        connections={connections}
        route={null}
        onSave={vi.fn()}
        title="Agent model"
        filterCards={["claude", "ollama"]}
      />,
    );

    fireEvent.mouseDown(screen.getByLabelText(/connection/i));
    expect(screen.getByRole("option", { name: "Claude" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Ollama" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Codex" })).toBeNull();
  });

  it("allowClear renders a Clear button that calls onSave(null)", async () => {
    vi.mocked(listConnectionModels).mockResolvedValueOnce(models);
    const onSave = vi.fn().mockResolvedValue(undefined);
    const connections = [
      makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true }),
    ];
    render(
      <ModelRoutePicker
        connections={connections}
        route={{ connection: "claude", model: "claude-opus-5" }}
        onSave={onSave}
        title="Agent model"
        allowClear
      />,
    );

    await vi.waitFor(() => {
      expect(listConnectionModels).toHaveBeenCalledWith("claude");
    });

    fireEvent.click(screen.getByRole("button", { name: /^clear$/i }));

    await vi.waitFor(() => {
      expect(onSave).toHaveBeenCalledWith(null);
    });
  });

  it("without allowClear, no Clear button is rendered", () => {
    const connections = [
      makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true }),
    ];
    render(
      <ModelRoutePicker
        connections={connections}
        route={null}
        onSave={vi.fn()}
        title="Agent model"
      />,
    );

    expect(screen.queryByRole("button", { name: /^clear$/i })).toBeNull();
  });

  it("without showTest, no Test connection button is rendered", () => {
    const connections = [
      makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true }),
    ];
    render(
      <ModelRoutePicker
        connections={connections}
        route={null}
        onSave={vi.fn()}
        title="Agent model"
      />,
    );

    expect(screen.queryByRole("button", { name: /test connection/i })).toBeNull();
    expect(testConnectionProvider).not.toHaveBeenCalled();
  });

  it("saving with a context window value calls onSave with contextWindow set", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const connections = [
      makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true }),
    ];
    render(
      <ModelRoutePicker
        connections={connections}
        route={{ connection: "claude", model: "claude-opus-5" }}
        onSave={onSave}
        title="Agent model"
      />,
    );

    fireEvent.change(screen.getByLabelText(/context window/i), {
      target: { value: "200000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await vi.waitFor(() => {
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({ contextWindow: 200000 }),
      );
    });
  });
});
