// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { getAgentConfig, updateAgentConfig } from "../api/client";
import type { AgentConfig } from "../api/types";
import { JobSearchPolicySection } from "./JobSearchPolicySection";
import { SettingsAutosaveProvider, SETTINGS_AUTOSAVE_DELAY_MS, useSettingsAutosaveCoordinator } from "./SettingsAutosave";

vi.mock("../api/client", () => ({ getAgentConfig: vi.fn(), updateAgentConfig: vi.fn() }));
const config = { cooldownDays: 90, cooldownDaysSameRole: null, cooldownDaysSameCompany: 0,
  blockedCompanies: ["untouched"] } as AgentConfig;
const mount = () => render(<SettingsAutosaveProvider><JobSearchPolicySection /></SettingsAutosaveProvider>);
afterEach(() => { cleanup(); vi.useRealTimers(); vi.clearAllMocks(); });

describe("job search policy autosave", () => {
  it("does not edit before load or on failed load", async () => {
    let resolve!: (cfg: AgentConfig) => void;
    vi.mocked(getAgentConfig).mockImplementationOnce(() => new Promise((ok) => { resolve = ok; }));
    const view = mount();
    expect(screen.queryByLabelText(/same role cooldown/i)).toBeNull();
    expect(updateAgentConfig).not.toHaveBeenCalled();
    await act(async () => resolve(config));
    expect((screen.getByLabelText(/same company cooldown/i) as HTMLInputElement).value).toBe("0");
    expect(updateAgentConfig).not.toHaveBeenCalled();
    view.unmount();
    vi.mocked(getAgentConfig).mockRejectedValueOnce(new Error("load failed"));
    mount();
    expect(await screen.findByText("load failed")).toBeTruthy();
    expect(screen.queryByLabelText(/cooldown days/i)).toBeNull();
  });

  it("debounces only the edited keys; blank sends null, zero disables and blur flushes", async () => {
    vi.mocked(getAgentConfig).mockResolvedValue(config);
    vi.mocked(updateAgentConfig).mockResolvedValue(config);
    mount();
    const role = await screen.findByLabelText(/same role cooldown/i);
    vi.useFakeTimers();
    fireEvent.change(role, { target: { value: "12" } });
    fireEvent.change(role, { target: { value: "13" } });
    expect(updateAgentConfig).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(SETTINGS_AUTOSAVE_DELAY_MS); });
    expect(updateAgentConfig).toHaveBeenCalledTimes(1);
    expect(updateAgentConfig).toHaveBeenLastCalledWith({ cooldownDaysSameRole: 13 });
    fireEvent.change(role, { target: { value: "" } });
    fireEvent.blur(role);
    await act(async () => { await Promise.resolve(); });
    expect(updateAgentConfig).toHaveBeenLastCalledWith({ cooldownDaysSameRole: null });
    expect(updateAgentConfig).not.toHaveBeenCalledWith(expect.objectContaining({ blockedCompanies: expect.anything() }));
    fireEvent.change(screen.getByLabelText(/cooldown days \(fallback\)/i), { target: { value: "0" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(SETTINGS_AUTOSAVE_DELAY_MS); });
    expect(updateAgentConfig).toHaveBeenLastCalledWith({ cooldownDays: 0 });
  });

  it("invalid drafts block close; failed drafts retry without normalizing newer input", async () => {
    vi.mocked(getAgentConfig).mockResolvedValue(config);
    let reject!: (error: Error) => void;
    vi.mocked(updateAgentConfig).mockImplementationOnce(() => new Promise((_ok, fail) => { reject = fail; }))
      .mockResolvedValue(config);
    let coordinator!: ReturnType<typeof useSettingsAutosaveCoordinator>;
    function Capture() { coordinator = useSettingsAutosaveCoordinator(); return null; }
    render(<SettingsAutosaveProvider><Capture /><JobSearchPolicySection /></SettingsAutosaveProvider>);
    const company = await screen.findByLabelText(/same company cooldown/i);
    fireEvent.change(company, { target: { value: "9999999999999999999999" } });
    expect(await coordinator.flushAndWait()).toBe(false);
    expect(updateAgentConfig).not.toHaveBeenCalled();
    fireEvent.change(company, { target: { value: "8" } });
    fireEvent.blur(company);
    await vi.waitFor(() => expect(updateAgentConfig).toHaveBeenCalledWith({ cooldownDaysSameCompany: 8 }));
    reject(new Error("offline"));
    expect(await screen.findByRole("button", { name: /retry same company/i })).toBeTruthy();
    expect(await coordinator.flushAndWait()).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /retry same company/i }));
    expect(await coordinator.flushAndWait()).toBe(true);
    expect((company as HTMLInputElement).value).toBe("8");
  });
});
