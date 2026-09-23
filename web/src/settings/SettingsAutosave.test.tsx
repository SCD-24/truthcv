// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { SettingsAutosaveCoordinator, SettingsAutosaveProvider, useSettingsAutosave, SETTINGS_AUTOSAVE_DELAY_MS } from "./SettingsAutosave";

function deferred() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
const tick = async () => { await act(async () => { await Promise.resolve(); }); };
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("Settings autosave coordinator", () => {
  it("coalesces latest pending per key without losing independent keys or overlapping writes", async () => {
    const coordinator = new SettingsAutosaveCoordinator();
    const first = deferred();
    const writes: string[] = [];
    const write = vi.fn((value: string) => {
      writes.push(value);
      return value === "a1" ? first.promise : Promise.resolve();
    });
    coordinator.edit("a", "a1", write);
    await tick();
    coordinator.edit("a", "a2", write);
    coordinator.edit("b", "b1", write);
    coordinator.edit("a", "a3", write);
    expect(writes).toEqual(["a1"]);
    first.resolve();
    expect(await coordinator.flushAndWait()).toBe(true);
    expect(writes).toEqual(["a1", "a3", "b1"]);
    expect(coordinator.status("a").status).toBe("saved");
  });

  it("debounces typing, flushes on blur, blocks invalid close and recovers failed drafts", async () => {
    vi.useFakeTimers();
    const coordinator = new SettingsAutosaveCoordinator();
    const write = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(undefined);
    coordinator.edit("route", "x", write, { debounce: true });
    expect(coordinator.status("route").status).toBe("pending");
    await vi.advanceTimersByTimeAsync(SETTINGS_AUTOSAVE_DELAY_MS - 1);
    expect(write).not.toHaveBeenCalled();
    expect(await coordinator.flushAndWait()).toBe(false);
    expect(coordinator.status("route")).toEqual({ status: "error", error: "offline" });
    coordinator.retry("route");
    expect(await coordinator.flushAndWait()).toBe(true);
    coordinator.edit("route", "", write, { valid: false });
    expect(await coordinator.flushAndWait()).toBe(false);
    coordinator.discard();
    expect(await coordinator.flushAndWait()).toBe(true);
  });

  it("discard cancels queued edits before waiting for an active write", async () => {
    const coordinator = new SettingsAutosaveCoordinator();
    const active = deferred();
    const write = vi.fn().mockReturnValueOnce(active.promise).mockResolvedValue(undefined);
    coordinator.edit("first", "active", write);
    await tick();
    coordinator.edit("second", "queued", write);
    const done = coordinator.discardAndWait();
    expect(coordinator.status("second").status).toBe("idle");
    expect(write).toHaveBeenCalledTimes(1);
    coordinator.edit("second", "late edit", write);
    active.resolve();
    await done;
    expect(write).toHaveBeenCalledTimes(1);
    expect(coordinator.status("first").status).toBe("idle");
  });

  it("StrictMode effect replay keeps provider and local coordinators usable", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    function Probe() {
      const autosave = useSettingsAutosave("key");
      return <button onClick={() => autosave.edit("choice", write)}>{autosave.status}</button>;
    }
    const provider = render(<StrictMode><SettingsAutosaveProvider><Probe /></SettingsAutosaveProvider></StrictMode>);
    fireEvent.click(screen.getByRole("button"));
    await vi.waitFor(() => expect(screen.getByRole("button").textContent).toBe("saved"));
    provider.unmount();
    render(<StrictMode><Probe /></StrictMode>);
    fireEvent.click(screen.getByRole("button"));
    await vi.waitFor(() => expect(write).toHaveBeenCalledTimes(2));
  });

  it("an older completion cannot mark a newer draft saved; unmount removes subscriptions and timers", async () => {
    vi.useFakeTimers();
    const coordinator = new SettingsAutosaveCoordinator();
    const first = deferred();
    const write = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(undefined);
    coordinator.edit("a", "old", write);
    await tick();
    coordinator.edit("a", "new", write, { debounce: true });
    first.resolve();
    await tick();
    expect(coordinator.status("a").status).toBe("pending");
    expect(await coordinator.flushAndWait()).toBe(true);
    expect(write).toHaveBeenCalledTimes(2);

    function Probe() {
      const autosave = useSettingsAutosave("probe");
      return <button onClick={() => autosave.edit("typed", write, { debounce: true })}>{autosave.status}</button>;
    }
    const view = render(<SettingsAutosaveProvider><Probe /></SettingsAutosaveProvider>);
    expect(screen.getByRole("button").textContent).toBe("idle");
    act(() => { screen.getByRole("button").click(); });
    view.unmount();
    await vi.advanceTimersByTimeAsync(SETTINGS_AUTOSAVE_DELAY_MS);
    expect(write).toHaveBeenCalledTimes(2);
  });
});
