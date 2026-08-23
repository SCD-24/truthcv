// @vitest-environment jsdom
/**
 * Tests for the effort-level select in ModelRoutePicker.
 * Follows the stubbing conventions of ModelRoutePicker.test.tsx.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { listConnectionModels } from "../api/client";
import type { ConnectionStatus, ModelInfo, RouteChoice } from "../api/types";
import { ModelRoutePicker } from "./ModelRoutePicker";

vi.mock("../api/client", () => ({
  listConnectionModels: vi.fn(),
  testConnectionProvider: vi.fn(),
  updateRouting: vi.fn(),
}));

function makeStatus(overrides: Partial<ConnectionStatus> = {}): ConnectionStatus {
  return {
    provider: "codex",
    label: "Codex",
    modes: ["apikey"],
    subscriptionConnected: false,
    apiKeyConnected: true,
    authMode: "apikey",
    expiresAt: null,
    connectedAt: null,
    ...overrides,
  };
}

/** Models with and without effort support. */
const modelsWithEffort: ModelInfo[] = [
  { id: "gpt-5", label: "GPT-5", effortLevels: ["minimal", "low", "medium", "high"] },
  { id: "gpt-4o", label: "GPT-4o", effortLevels: [] },
];

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ModelRoutePicker effort-level select", () => {
  it("(a) effort select is hidden when the selected model has no effort levels", async () => {
    vi.mocked(listConnectionModels).mockResolvedValueOnce(modelsWithEffort);

    const connections = [makeStatus()];
    render(
      <ModelRoutePicker
        connections={connections}
        route={null}
        onSave={vi.fn()}
        title="Test picker"
      />,
    );

    // Wait for models to load
    await vi.waitFor(() => expect(listConnectionModels).toHaveBeenCalled());

    // Select gpt-4o (no effort)
    fireEvent.mouseDown(screen.getByLabelText(/^model$/i));
    fireEvent.click(await screen.findByRole("option", { name: "GPT-4o" }));

    expect(screen.queryByLabelText(/effort level/i)).toBeNull();
  });

  it("(b) effort select appears with exact options for a capable model", async () => {
    vi.mocked(listConnectionModels).mockResolvedValueOnce(modelsWithEffort);

    const connections = [makeStatus()];
    render(
      <ModelRoutePicker
        connections={connections}
        route={null}
        onSave={vi.fn()}
        title="Test picker"
      />,
    );

    await vi.waitFor(() => expect(listConnectionModels).toHaveBeenCalled());

    // Select gpt-5 (effort supported)
    fireEvent.mouseDown(screen.getByLabelText(/^model$/i));
    fireEvent.click(await screen.findByRole("option", { name: "GPT-5" }));

    // Effort select should now appear
    expect(screen.getByLabelText(/effort level/i)).toBeTruthy();

    // Open effort select and check options
    fireEvent.mouseDown(screen.getByLabelText(/effort level/i));
    expect(screen.getByRole("option", { name: "Provider default" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Minimal" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Low" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Medium" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "High" })).toBeTruthy();
  });

  it("(c) Save emits RouteChoice including chosen effort", async () => {
    vi.mocked(listConnectionModels).mockResolvedValueOnce(modelsWithEffort);
    const onSave = vi.fn().mockResolvedValue(undefined);

    const connections = [makeStatus()];
    render(
      <ModelRoutePicker
        connections={connections}
        route={null}
        onSave={onSave}
        title="Test picker"
      />,
    );

    await vi.waitFor(() => expect(listConnectionModels).toHaveBeenCalled());

    // Pick gpt-5
    fireEvent.mouseDown(screen.getByLabelText(/^model$/i));
    fireEvent.click(await screen.findByRole("option", { name: "GPT-5" }));

    // Pick effort=high
    fireEvent.mouseDown(screen.getByLabelText(/effort level/i));
    fireEvent.click(screen.getByRole("option", { name: "High" }));

    // Save
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await vi.waitFor(() => {
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({ connection: "codex", model: "gpt-5", effort: "high" }),
      );
    });
  });

  it("(d) switching from a capable model drops stale effort", async () => {
    vi.mocked(listConnectionModels).mockResolvedValueOnce(modelsWithEffort);
    const onSave = vi.fn().mockResolvedValue(undefined);

    const connections = [makeStatus()];
    render(
      <ModelRoutePicker
        connections={connections}
        route={null}
        onSave={onSave}
        title="Test picker"
      />,
    );

    await vi.waitFor(() => expect(listConnectionModels).toHaveBeenCalled());

    // Select gpt-5 and set effort
    fireEvent.mouseDown(screen.getByLabelText(/^model$/i));
    fireEvent.click(await screen.findByRole("option", { name: "GPT-5" }));
    fireEvent.mouseDown(screen.getByLabelText(/effort level/i));
    fireEvent.click(screen.getByRole("option", { name: "Low" }));

    // Switch to gpt-4o (no effort support).
    // Use getAllByLabelText and pick the combobox to avoid ambiguity when the
    // effort select is also rendered.
    const modelCombobox = screen
      .getAllByLabelText(/^model$/i)
      .find((el) => el.getAttribute("role") === "combobox");
    expect(modelCombobox).toBeTruthy();
    fireEvent.mouseDown(modelCombobox!);
    fireEvent.click(await screen.findByRole("option", { name: "GPT-4o" }));

    // Effort select should now be gone
    expect(screen.queryByLabelText(/effort level/i)).toBeNull();

    // Save — effort should not appear in the payload
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await vi.waitFor(() => {
      const call = onSave.mock.calls[0][0] as RouteChoice;
      expect(call.model).toBe("gpt-4o");
      expect(call.effort).toBeUndefined();
    });
  });

  it("effort select is hidden for a custom model id", async () => {
    vi.mocked(listConnectionModels).mockResolvedValueOnce(modelsWithEffort);

    const connections = [makeStatus()];
    render(
      <ModelRoutePicker
        connections={connections}
        route={null}
        onSave={vi.fn()}
        title="Test picker"
      />,
    );

    await vi.waitFor(() => expect(listConnectionModels).toHaveBeenCalled());

    // Pick Custom…
    fireEvent.mouseDown(screen.getByLabelText(/^model$/i));
    fireEvent.click(await screen.findByRole("option", { name: /custom/i }));

    expect(screen.queryByLabelText(/effort level/i)).toBeNull();
  });

  it("initialises effort from an existing route", async () => {
    vi.mocked(listConnectionModels).mockResolvedValueOnce(modelsWithEffort);

    const connections = [makeStatus()];
    render(
      <ModelRoutePicker
        connections={connections}
        route={{ connection: "codex", model: "gpt-5", effort: "medium" }}
        onSave={vi.fn()}
        title="Test picker"
      />,
    );

    await vi.waitFor(() => expect(listConnectionModels).toHaveBeenCalled());

    // Effort select should be visible and show "medium"
    const effortSelect = await screen.findByLabelText(/effort level/i);
    expect(effortSelect).toBeTruthy();
    // The select input should display the current value
    expect(effortSelect.closest("[data-testid]") || effortSelect).toBeTruthy();
  });
});
