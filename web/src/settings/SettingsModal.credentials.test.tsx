// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { getAgentConfig, getGmailStatus, getJevSettings, getOnboarding, getRouting, listConnections,
  saveConnectionKey, saveJevSettings, updateAgentConfig, updateRouting } from "../api/client";
import type { AgentConfig, ConnectionList, GmailStatus, JevSettings } from "../api/types";
import { WizardProvider } from "../wizard/store";
import { SettingsModal } from "./SettingsModal";

vi.mock("../api/client", () => ({
  getAgentConfig: vi.fn(), getGmailStatus: vi.fn(), getJevSettings: vi.fn(), getOnboarding: vi.fn(),
  getRouting: vi.fn(), listConnections: vi.fn(), listConnectionModels: vi.fn(),
  saveConnectionKey: vi.fn(), saveJevSettings: vi.fn(), updateAgentConfig: vi.fn(),
  updateRouting: vi.fn(),
}));
const jev: JevSettings = { keySet: true, useForScreening: false,
  useForEmailTracking: false, encryptionAvailable: true };
const gmail: GmailStatus = { connected: false, email: null, reauthRequired: false, trackingEnabled: false };
const accounts: ConnectionList = { encryptionAvailable: true, connections: [{
  provider: "claude", label: "Claude", modes: ["apikey"], subscriptionConnected: false,
  apiKeyConnected: true, authMode: "apikey", expiresAt: null, connectedAt: null,
}] };
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Settings modal credential boundary", () => {
  it("Jev credentials stay manual and Gmail/Jev toggles persist immediately without account controls", async () => {
    vi.mocked(getOnboarding).mockResolvedValue({ providerDone: true, hasProfile: false,
      cvReviewedAt: null, tourSeenAt: null, complete: false });
    vi.mocked(listConnections).mockResolvedValue(accounts);
    vi.mocked(getRouting).mockResolvedValue({ default: null, agent: null, tasks: {} });
    vi.mocked(getAgentConfig).mockResolvedValue({ cooldownDays: 90,
      cooldownDaysSameRole: null, cooldownDaysSameCompany: null } as AgentConfig);
    vi.mocked(getJevSettings).mockResolvedValue(jev);
    vi.mocked(getGmailStatus).mockResolvedValue(gmail);
    vi.mocked(saveJevSettings).mockImplementation(async (patch) => ({ ...jev, ...patch }));
    vi.mocked(saveConnectionKey).mockResolvedValue([]);
    render(<WizardProvider><SettingsModal onClose={vi.fn()} /></WizardProvider>);
    const jevKey = await screen.findByLabelText("Jev API key");
    fireEvent.change(jevKey, { target: { value: "not-a-real-key" } });
    expect(screen.queryByLabelText("API key")).toBeNull();
    expect(listConnections).not.toHaveBeenCalled();
    expect(getRouting).not.toHaveBeenCalled();
    expect(saveConnectionKey).not.toHaveBeenCalled();
    expect(saveJevSettings).not.toHaveBeenCalled();
    expect(updateRouting).not.toHaveBeenCalled();
    expect(updateAgentConfig).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox", { name: /use jev for screening/i }));
    await vi.waitFor(() => expect(saveJevSettings).toHaveBeenCalledWith({ useForScreening: true }));
    fireEvent.click(screen.getByRole("checkbox", { name: /enable email response tracking/i }));
    await vi.waitFor(() => expect(saveJevSettings).toHaveBeenCalledWith({ useForEmailTracking: true }));
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));
    await vi.waitFor(() => expect(saveJevSettings).toHaveBeenCalledWith({ apiKey: "not-a-real-key" }));
    expect(saveConnectionKey).not.toHaveBeenCalled();
  });
});
