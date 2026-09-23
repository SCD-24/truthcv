// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { listConnectionModels } from "../api/client";
import type { ConnectionStatus } from "../api/types";
import { ModelRoutePicker } from "./ModelRoutePicker";

vi.mock("../api/client", () => ({ listConnectionModels: vi.fn(), testConnectionProvider: vi.fn() }));
const connected = (provider: string): ConnectionStatus => ({
  provider, label: provider, modes: ["apikey"], subscriptionConnected: false,
  apiKeyConnected: true, authMode: "apikey", expiresAt: null, connectedAt: null,
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("initial and reconciled provider default", () => {
  it("does not write on hydration; explicit fallback commit works with a sole provider", async () => {
    vi.mocked(listConnectionModels).mockResolvedValue([]);
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ModelRoutePicker title="Default" autosaveKey="default" allowDefaultCommit
      connections={[connected("a")]} route={null} onSave={onSave} />);
    await vi.waitFor(() => expect(listConnectionModels).toHaveBeenCalledWith("a"));
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByText("Saved.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Use this provider default" }));
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledWith({ connection: "a", model: "" }));
    expect(await screen.findByText("Saved.")).toBeTruthy();
  });

  it("does not commit a disconnected route through reconciliation or a stale model-list response", async () => {
    let finish!: (models: { id: string; label: string }[]) => void;
    vi.mocked(listConnectionModels).mockImplementation((provider) => provider === "a"
      ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve([]));
    const onSave = vi.fn().mockResolvedValue(undefined);
    const props = { title: "Default", autosaveKey: "default", allowDefaultCommit: true, onSave };
    const view = render(<ModelRoutePicker {...props} connections={[connected("a"), connected("b")]}
      route={{ connection: "a", model: "m" }} />);
    await vi.waitFor(() => expect(listConnectionModels).toHaveBeenCalledWith("a"));
    view.rerender(<ModelRoutePicker {...props} connections={[connected("b")]} route={{ connection: "a", model: "m" }} />);
    await vi.waitFor(() => expect(listConnectionModels).toHaveBeenCalledWith("b"));
    finish([{ id: "m", label: "Old model" }]);
    await Promise.resolve();
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByText("Old model")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Use this provider default" }));
    await vi.waitFor(() => expect(onSave).toHaveBeenCalledWith({ connection: "b", model: "" }));
  });

  it("rejects unsafe integer context before a fallback commit", async () => {
    vi.mocked(listConnectionModels).mockResolvedValue([]);
    const onSave = vi.fn();
    render(<ModelRoutePicker title="Default" autosaveKey="default" allowDefaultCommit
      connections={[connected("a")]} route={null} onSave={onSave} />);
    const context = screen.getByRole("spinbutton", { name: /context window/i });
    fireEvent.change(context, { target: { value: "9007199254740992" } });
    expect((screen.getByRole("button", { name: "Use this provider default" }) as HTMLButtonElement).disabled).toBe(true);
    expect(onSave).not.toHaveBeenCalled();
  });
});
