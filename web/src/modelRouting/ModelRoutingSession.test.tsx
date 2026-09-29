// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { StrictMode, useState } from "react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { ModelRoutingSession, useModelRoutingReload } from "./ModelRoutingSession";
import { useSettingsAutosave, useSettingsAutosaveCoordinator } from "../settings/SettingsAutosave";

afterEach(() => { cleanup(); vi.clearAllMocks(); });
function Probe({ write }: { write: (value: string) => Promise<void> }) {
  const autosave = useSettingsAutosave("routing:default");
  const reload = useModelRoutingReload();
  const navigate = useNavigate();
  return <>
    <span data-testid="locked">{String(autosave.locked)}</span>
    <button onClick={() => autosave.edit("typed", write, { debounce: true, draft: { text: "typed" } })}>Edit</button>
    <button onClick={() => navigate("/elsewhere")}>Navigate</button>
    <span data-testid="draft">{autosave.draft<{ text: string }>()?.text ?? "empty"}</span>
    <span data-testid="reload">{reload}</span>
  </>;
}
function DiscardProbe({ write }: { write: (value: string) => Promise<void> }) {
  const coordinator = useSettingsAutosaveCoordinator();
  const [shown, setShown] = useState(true);
  return <>
    <button onClick={() => setShown((value) => !value)}>Toggle probe</button>
    {shown && <Probe write={write} />}
    <button onClick={() => { void coordinator.discardAndWait(); }}>Discard in probe</button>
  </>;
}

describe("shell-lived routing session", () => {
  it("flushes debounced edits on navigation and retains the full draft", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    render(<MemoryRouter initialEntries={["/model-routing"]}><ModelRoutingSession><Probe write={write} /></ModelRoutingSession></MemoryRouter>);
    fireEvent.click(screen.getByText("Edit"));
    expect(write).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Navigate"));
    await vi.waitFor(() => expect(write).toHaveBeenCalledWith("typed"));
    expect(screen.getByTestId("draft").textContent).toBe("typed");
  });

  it("StrictMode subscriptions cannot revive a discard while an active write remains", async () => {
    let finish!: () => void;
    const write = vi.fn(() => new Promise<void>((resolve) => { finish = resolve; }));
    render(<StrictMode><MemoryRouter><ModelRoutingSession><DiscardProbe write={write} /></ModelRoutingSession></MemoryRouter></StrictMode>);
    fireEvent.click(screen.getByText("Edit"));
    fireEvent.click(screen.getByText("Navigate"));
    await vi.waitFor(() => expect(write).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText("Discard in probe"));
    fireEvent.click(screen.getByText("Toggle probe"));
    fireEvent.click(screen.getByText("Toggle probe"));
    expect(screen.getByTestId("locked").textContent).toBe("true");
    fireEvent.click(screen.getByText("Edit"));
    expect(screen.getByTestId("draft").textContent).toBe("empty");
    expect(screen.getByText(/default: saving/)).toBeTruthy();
    await act(async () => { finish(); });
    expect(screen.getByTestId("locked").textContent).toBe("true");
  });

  it("recovers errors outside the page and waits for active writes before discard reload", async () => {
    let reject!: (error: Error) => void;
    let finish!: () => void;
    const write = vi.fn().mockImplementationOnce(() => new Promise<void>((_ok, fail) => { reject = fail; }))
      .mockImplementationOnce(() => new Promise<void>((ok) => { finish = ok; }));
    render(<MemoryRouter><ModelRoutingSession><Probe write={write} /></ModelRoutingSession></MemoryRouter>);
    fireEvent.click(screen.getByText("Edit"));
    fireEvent.click(screen.getByText("Navigate"));
    await vi.waitFor(() => expect(write).toHaveBeenCalledTimes(1));
    await act(async () => { reject(new Error("offline")); });
    expect(screen.getByText(/offline/)).toBeTruthy();
    fireEvent.click(screen.getByText("Retry save"));
    await vi.waitFor(() => expect(write).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByText("Discard routing changes"));
    expect(screen.getByTestId("reload").textContent).toBe("0");
    await act(async () => { finish(); });
    expect(screen.getByTestId("reload").textContent).toBe("1");
    expect(screen.queryByText(/offline/)).toBeNull();
  });
});
