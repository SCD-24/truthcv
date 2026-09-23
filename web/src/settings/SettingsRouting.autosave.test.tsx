// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { listConnectionModels, updateRouting } from "../api/client";
import type { ConnectionStatus, Routing } from "../api/types";
import { DefaultModelSection } from "./DefaultModelSection";
import { TaskModelsSection } from "./TaskModelsSection";
import { SettingsAutosaveProvider } from "./SettingsAutosave";

vi.mock("../api/client", () => ({ listConnectionModels: vi.fn(), updateRouting: vi.fn(), testConnectionProvider: vi.fn() }));
const connection: ConnectionStatus = {
  provider: "claude", label: "Claude", modes: ["subscription"], subscriptionConnected: true,
  apiKeyConnected: false, authMode: "subscription", expiresAt: null, connectedAt: null,
};
const routing: Routing = { default: null, tasks: {}, agent: null };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((ok) => { resolve = ok; });
  return { promise, resolve };
}
function Session() {
  return <>
    <DefaultModelSection autosave connections={[connection]} routing={routing} onSaved={vi.fn()} />
    <TaskModelsSection connections={[connection]} routing={routing} onSaved={vi.fn()} />
  </>;
}
async function chooseModel(row: number) {
  fireEvent.mouseDown(screen.getAllByLabelText(/^model$/i)[row]);
  fireEvent.click(await screen.findByRole("option", { name: "Model M" }));
}
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("settings routing session", () => {
  it("serializes default and task writes even across different picker rows", async () => {
    vi.mocked(listConnectionModels).mockResolvedValue([{ id: "m", label: "Model M" }]);
    const first = deferred<Routing>();
    vi.mocked(updateRouting).mockReturnValueOnce(first.promise).mockResolvedValue(routing);
    render(<SettingsAutosaveProvider><Session /></SettingsAutosaveProvider>);
    await screen.findAllByRole("button", { name: "Reload" });
    await vi.waitFor(() => expect(listConnectionModels).toHaveBeenCalled());
    await chooseModel(0);
    await vi.waitFor(() => expect(updateRouting).toHaveBeenCalledTimes(1));
    await chooseModel(1);
    await Promise.resolve();
    expect(updateRouting).toHaveBeenCalledTimes(1);
    first.resolve(routing);
    await vi.waitFor(() => expect(updateRouting).toHaveBeenNthCalledWith(2, { tasks: { truth_extract: { connection: "claude", model: "m" } } }));
    expect(updateRouting).toHaveBeenNthCalledWith(1, { default: { connection: "claude", model: "m" } });
  });

  it("queued clear supersedes a task choice without recreating its route", async () => {
    vi.mocked(listConnectionModels).mockResolvedValue([{ id: "m", label: "Model M" }]);
    const first = deferred<Routing>();
    vi.mocked(updateRouting).mockReturnValueOnce(first.promise).mockResolvedValue(routing);
    render(<SettingsAutosaveProvider><Session /></SettingsAutosaveProvider>);
    await vi.waitFor(() => expect(listConnectionModels).toHaveBeenCalled());
    await chooseModel(0);
    await vi.waitFor(() => expect(updateRouting).toHaveBeenCalledTimes(1));
    await chooseModel(1);
    fireEvent.click(screen.getAllByRole("button", { name: "Clear" })[0]);
    first.resolve(routing);
    await vi.waitFor(() => expect(updateRouting).toHaveBeenCalledTimes(2));
    expect(updateRouting).toHaveBeenLastCalledWith({ tasks: { truth_extract: null } });
  });
});
