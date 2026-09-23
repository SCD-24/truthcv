// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { listConnectionModels } from "../api/client";
import type { ConnectionStatus, ModelInfo } from "../api/types";
import { ModelRoutePicker } from "./ModelRoutePicker";

vi.mock("../api/client", () => ({ listConnectionModels: vi.fn(), testConnectionProvider: vi.fn() }));
const connected = (provider: string): ConnectionStatus => ({
  provider, label: provider, modes: ["apikey"], subscriptionConnected: false,
  apiKeyConnected: true, authMode: "apikey", expiresAt: null, connectedAt: null,
});
const models: ModelInfo[] = [{ id: "m", label: "Model M", effortLevels: ["high"] }];
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("opt-in picker autosave", () => {
  it("never saves hydration or reload, but saves committed provider default, model and effort", async () => {
    vi.mocked(listConnectionModels).mockResolvedValue(models);
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ModelRoutePicker title="Default" autosaveKey="default" connections={[connected("a"), connected("b")]}
      route={{ connection: "a", model: "m" }} onSave={onSave} />);
    await vi.waitFor(() => expect(listConnectionModels).toHaveBeenCalledWith("a"));
    await vi.waitFor(() => expect((screen.getByRole("button", { name: "Reload" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.mouseDown(screen.getByLabelText(/^model$/i));
    fireEvent.click(await screen.findByRole("option", { name: "Provider default" }));
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledWith({ connection: "a", model: "" }));
    fireEvent.mouseDown(screen.getByLabelText(/^model$/i));
    fireEvent.click(await screen.findByRole("option", { name: "Model M" }));
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledWith({ connection: "a", model: "m" }));
    fireEvent.mouseDown(screen.getByLabelText(/effort level/i));
    fireEvent.click(screen.getByRole("option", { name: "High" }));
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledWith({ connection: "a", model: "m", effort: "high" }));
    fireEvent.mouseDown(screen.getByLabelText(/connection/i));
    fireEvent.click(screen.getByRole("option", { name: "b" }));
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledWith({ connection: "b", model: "" }));
  });

  it("rejects incomplete custom and invalid context, flushes context on blur and clears null", async () => {
    vi.mocked(listConnectionModels).mockResolvedValue(models);
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ModelRoutePicker title="Task" autosaveKey="task" allowClear connections={[connected("a")]}
      route={null} onSave={onSave} />);
    await vi.waitFor(() => expect(listConnectionModels).toHaveBeenCalled());
    fireEvent.mouseDown(screen.getByLabelText(/^model$/i));
    fireEvent.click(screen.getByRole("option", { name: /custom/i }));
    expect(screen.getByRole("status").textContent).toMatch(/complete a valid/i);
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: "Custom model id" }), { target: { value: "custom-id" } });
    fireEvent.blur(screen.getByRole("textbox", { name: "Custom model id" }));
    fireEvent.change(screen.getByLabelText(/context window/i), { target: { value: "8191" } });
    expect(screen.getByRole("status").textContent).toMatch(/complete a valid/i);
    fireEvent.change(screen.getByLabelText(/context window/i), { target: { value: "8192" } });
    fireEvent.blur(screen.getByLabelText(/context window/i));
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledWith({ connection: "a", model: "custom-id", contextWindow: 8192 }));
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await vi.waitFor(() => expect(onSave).toHaveBeenLastCalledWith(null));
    expect(screen.queryByRole("button", { name: /^save$/i })).toBeNull();
  });
});
