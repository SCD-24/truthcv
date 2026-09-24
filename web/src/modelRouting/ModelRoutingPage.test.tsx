// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { getRouting, listConnections, listConnectionModels, saveConnectionKey, updateRouting } from "../api/client";
import type { ConnectionList, ConnectionStatus, Routing } from "../api/types";
import { TASKS } from "../settings/TaskModelsSection";
import { ModelRoutingPage } from "./ModelRoutingPage";
import { ModelRoutingSession } from "./ModelRoutingSession";

vi.mock("../api/client", () => ({ getRouting: vi.fn(), listConnections: vi.fn(),
  listConnectionModels: vi.fn(), saveConnectionKey: vi.fn(), updateRouting: vi.fn(),
  testConnectionProvider: vi.fn() }));
const status = (provider: string): ConnectionStatus => ({ provider, label: provider,
  modes: ["apikey"], subscriptionConnected: false, apiKeyConnected: true,
  authMode: "apikey", connectedAt: null, expiresAt: null });
const accounts: ConnectionList = { encryptionAvailable: true,
  connections: [status("claude"), status("openrouter"), status("codex"), status("ollama")] };
const routing: Routing = { default: null, tasks: {}, agent: null };
function Host() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return <ModelRoutingSession>
    <button onClick={() => navigate(pathname === "/model-routing" ? "/analytics" : "/model-routing")}>Navigate</button>
    {pathname === "/model-routing" ? <ModelRoutingPage /> : <span>Analytics</span>}
  </ModelRoutingSession>;
}
function setup() {
  vi.mocked(getRouting).mockResolvedValue(routing);
  vi.mocked(listConnections).mockResolvedValue(accounts);
  vi.mocked(listConnectionModels).mockResolvedValue([{ id: "m", label: "Model M" }]);
  vi.mocked(updateRouting).mockResolvedValue(routing);
  render(<MemoryRouter initialEntries={["/model-routing"]}><Host /></MemoryRouter>);
}
afterEach(() => { cleanup(); vi.clearAllMocks(); });

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((finish) => { resolve = finish; });
  return { promise, resolve };
}

describe("Model routing page", () => {
  it("shows Accounts and all seven routing rows with purpose descriptions", async () => {
    setup();
    expect(await screen.findByText("Accounts")).toBeTruthy();
    expect(screen.getByText("Default model")).toBeTruthy();
    expect(screen.getByText(/Used when a task has no override/)).toBeTruthy();
    for (const task of TASKS) expect(screen.getByText(task.description)).toBeTruthy();
    expect(screen.getByText("Application agent")).toBeTruthy();
    expect(screen.getByText(/Runs unattended job applications in the browser/)).toBeTruthy();
    expect(screen.getAllByLabelText(/^model$/i)).toHaveLength(7);
    expect(updateRouting).not.toHaveBeenCalled();
  });

  it("agent route filters out Ollama, saves the independent agent key, and clears it", async () => {
    setup();
    await screen.findByText("Application agent");
    fireEvent.mouseDown(screen.getAllByLabelText("Connection")[6]);
    expect(screen.queryByRole("option", { name: "ollama" })).toBeNull();
    expect(screen.getByRole("option", { name: "claude" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "openrouter" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "codex" })).toBeTruthy();
    fireEvent.click(screen.getByRole("option", { name: "claude" }));
    fireEvent.mouseDown(screen.getAllByLabelText(/^model$/i)[6]);
    fireEvent.click(await screen.findByRole("option", { name: "Model M" }));
    await vi.waitFor(() => expect(updateRouting).toHaveBeenCalledWith({ agent: { connection: "claude", model: "m" } }));
    fireEvent.click(screen.getAllByRole("button", { name: "Clear" })[5]);
    await vi.waitFor(() => expect(updateRouting).toHaveBeenCalledWith({ agent: null }));
  });

  it("keeps API keys manual and refreshes accounts after a save", async () => {
    vi.mocked(saveConnectionKey).mockResolvedValue([]);
    setup();
    fireEvent.change(await screen.findAllByLabelText("API key").then((keys) => keys[0]), { target: { value: "secret" } });
    expect(saveConnectionKey).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await vi.waitFor(() => expect(saveConnectionKey).toHaveBeenCalledWith("claude", { apiKey: "secret" }));
    await vi.waitFor(() => expect(listConnections).toHaveBeenCalledTimes(2));
  });

  it("keeps a discarded active write protected and routing controls locked across a real page return", async () => {
    const write = deferred<Routing>();
    const reloadRead = deferred<Routing>();
    setup();
    await screen.findByText("Application agent");
    vi.mocked(updateRouting).mockReturnValueOnce(write.promise);
    fireEvent.mouseDown(screen.getAllByLabelText(/^model$/i)[0]);
    fireEvent.click(await screen.findByRole("option", { name: "Model M" }));
    await vi.waitFor(() => expect(updateRouting).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText("Navigate"));
    fireEvent.click(screen.getByRole("button", { name: "Discard routing changes" }));
    const before = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(before);
    expect(before.defaultPrevented).toBe(true);
    expect(screen.getByText(/default: saving/)).toBeTruthy();
    fireEvent.click(screen.getByText("Navigate"));
    await screen.findByText("Application agent");
    const modelInput = screen.getAllByLabelText(/^model$/i)[0];
    expect((modelInput.closest("fieldset") as HTMLFieldSetElement).disabled).toBe(true);
    expect((screen.getAllByRole("button", { name: "Clear" })[0] as HTMLButtonElement).disabled).toBe(true);
    const context = screen.getAllByLabelText(/context window/i)[0] as HTMLInputElement;
    fireEvent.change(context, { target: { value: "8192" } });
    expect(context.value).toBe("0");
    expect((screen.getAllByRole("button", { name: "Save" })[0] as HTMLButtonElement).disabled).toBe(false);
    vi.mocked(getRouting).mockReturnValueOnce(reloadRead.promise);
    await act(async () => { write.resolve(routing); });
    expect(screen.queryByText(/default: saving/)).toBeNull();
    expect(screen.getByText(/Loading model routing/)).toBeTruthy();
    const after = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
    await act(async () => { reloadRead.resolve(routing); });
    await screen.findByText("Application agent");
    expect((screen.getAllByLabelText(/^model$/i)[0].closest("fieldset") as HTMLFieldSetElement).disabled).toBe(false);
  });

  it("lets a GET started after a save replace saved drafts, but not a pending write", async () => {
    const write = deferred<Routing>();
    setup();
    await screen.findByText("Application agent");
    vi.mocked(updateRouting).mockReturnValueOnce(write.promise);
    fireEvent.mouseDown(screen.getAllByLabelText(/^model$/i)[0]);
    fireEvent.click(await screen.findByRole("option", { name: "Model M" }));
    await vi.waitFor(() => expect(updateRouting).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText("Navigate"));
    fireEvent.click(screen.getByText("Navigate"));
    await screen.findByText("Application agent");
    expect((screen.getAllByLabelText(/^model$/i)[0] as HTMLInputElement).value).toBe("Model M");
    await act(async () => { write.resolve({ ...routing, default: { connection: "claude", model: "m" } }); });
    const serverRoute: Routing = { ...routing, default: { connection: "claude", model: "remote-id" } };
    vi.mocked(getRouting).mockResolvedValueOnce(serverRoute);
    fireEvent.click(screen.getByText("Navigate"));
    fireEvent.click(screen.getByText("Navigate"));
    expect((await screen.findByRole("textbox", { name: "Custom model id" }) as HTMLInputElement).value).toBe("remote-id");
    expect(updateRouting).toHaveBeenCalledTimes(1);
  });

  it("applies only the newest accounts refresh when requests complete in reverse", async () => {
    vi.mocked(saveConnectionKey).mockResolvedValue([]);
    setup();
    const keys = await screen.findAllByLabelText("API key");
    const first = deferred<ConnectionList>();
    const second = deferred<ConnectionList>();
    vi.mocked(listConnections).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    fireEvent.change(keys[0], { target: { value: "secret-a" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await vi.waitFor(() => expect(listConnections).toHaveBeenCalledTimes(2));
    fireEvent.change(keys[1], { target: { value: "secret-b" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Save" })[1]);
    await vi.waitFor(() => expect(listConnections).toHaveBeenCalledTimes(3));
    const newer = { ...accounts, connections: [status("codex")] };
    await act(async () => { second.resolve(newer); });
    expect(screen.getAllByLabelText("API key")).toHaveLength(1);
    await act(async () => { first.resolve(accounts); });
    expect(screen.getAllByLabelText("API key")).toHaveLength(1);
  });

  it("shows a retry on load failure, and restores drafts despite a stale GET on return", async () => {
    vi.mocked(getRouting).mockRejectedValueOnce(new Error("offline")).mockResolvedValue(routing);
    vi.mocked(listConnections).mockResolvedValue(accounts);
    vi.mocked(listConnectionModels).mockResolvedValue([{ id: "m", label: "Model M" }]);
    vi.mocked(updateRouting).mockRejectedValueOnce(new Error("save offline"));
    render(<MemoryRouter initialEntries={["/model-routing"]}><Host /></MemoryRouter>);
    expect(await screen.findByText(/offline/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    await screen.findByText("Application agent");
    fireEvent.mouseDown(screen.getAllByLabelText(/^model$/i)[0]);
    fireEvent.click(await screen.findByRole("option", { name: "Model M" }));
    await vi.waitFor(() => expect(screen.getAllByText(/save offline/)[0]).toBeTruthy());
    fireEvent.click(screen.getByText("Navigate"));
    expect(screen.getAllByText(/save offline/)[0]).toBeTruthy();
    fireEvent.click(screen.getByText("Navigate"));
    await screen.findByText("Default model");
    expect(screen.getByText(/Save failed: save offline/)).toBeTruthy();
  });
});
