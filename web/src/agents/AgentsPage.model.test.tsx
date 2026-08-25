// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  getAgentConfig,
  getAgentStatus,
  getProfileAnswers,
  getRouting,
  listConnectionModels,
  listConnections,
  triggerAgentRun,
  updateRouting,
} from "../api/client";
import type { AgentConfig, AgentStatus, ConnectionList, ConnectionStatus, ProfileAnswers, Routing } from "../api/types";
import { AgentsPage } from "./AgentsPage";

/** Mirrors AccountsSection.test.tsx's boundary choice — mock the API client
 * module directly and render with @testing-library/react + jsdom. */
vi.mock("../api/client", () => ({
  getAgentConfig: vi.fn(),
  getAgentStatus: vi.fn(),
  getProfileAnswers: vi.fn(),
  getRouting: vi.fn(),
  listConnections: vi.fn(),
  listConnectionModels: vi.fn(),
  listRuns: vi.fn().mockResolvedValue([]),
  triggerAgentRun: vi.fn(),
  updateAgentConfig: vi.fn(),
  saveProfileAnswers: vi.fn(),
  updateRouting: vi.fn(),
  getSigninQueue: vi.fn().mockResolvedValue({ sites: [] }),
}));

function makeConfig(overrides: Partial<AgentConfig> = {}): AgentConfig {
  return {
    mode: "full",
    enabled: true,
    blockedCompanies: [],
    runAt: ["09:00"],
    runDays: ["mon"],
    profiles: [],
    targetCompanies: [],
    cooldownDays: null,
    cooldownDaysSameRole: null,
    cooldownDaysSameCompany: null,
    maxApplicationsPerRun: null,
    maxPostingAgeDays: null,
    companyBoards: [],
    ...overrides,
  };
}

function makeAnswers(): ProfileAnswers {
  return {
    phone: "",
    workAuthorisation: "",
    noticePeriod: "",
    locationPreference: "",
    canonicalCvAssetId: null,
    name: "",
    email: "",
    linkedin: "",
    github: "",
    website: "",
    workAuthorisationNote: "",
  requiresSponsorship: "",
    authorizedNonGermanCountry: "",
    languages: "",
    highestRelevantDegree: "",
    otherDegree: "",
    csDegree: "",
    gpa: "",
    gender: "",
    yearsOfExperience: "",
    currentRole: "",
    howDidYouHear: "",
  };
}

function makeStatus(overrides: Partial<ConnectionStatus> = {}): ConnectionStatus {
  return {
    provider: "claude",
    label: "Claude",
    modes: ["subscription"],
    subscriptionConnected: true,
    apiKeyConnected: false,
    authMode: "subscription",
    expiresAt: null,
    connectedAt: null,
    ...overrides,
  };
}

function makeRouting(overrides: Partial<Routing> = {}): Routing {
  return {
    tasks: {},
    agent: null,
    default: null,
    ...overrides,
  };
}

function makeAgentStatus(overrides: Partial<AgentStatus> = {}): AgentStatus {
  return {
    running: false,
    cancelling: false,
    lastStartedAt: null,
    lastFinishedAt: null,
    lastExitCode: null,
    lastCancelled: false,
    ...overrides,
  };
}

async function renderLoaded(connections: ConnectionList, routing: Routing, agentConfig?: Partial<AgentConfig>) {
  vi.mocked(getAgentConfig).mockResolvedValue(makeConfig(agentConfig));
  vi.mocked(getAgentStatus).mockResolvedValue(makeAgentStatus());
  vi.mocked(getProfileAnswers).mockResolvedValue(makeAnswers());
  vi.mocked(getRouting).mockResolvedValue(routing);
  vi.mocked(listConnections).mockResolvedValue(connections);
  vi.mocked(listConnectionModels).mockResolvedValue([]);
  render(<MemoryRouter><AgentsPage onBack={vi.fn()} /></MemoryRouter>);
  await screen.findByRole("heading", { name: "Model" });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AgentsPage model section", () => {
  it("lists the Anthropic-compatible connections and no others", async () => {
    // The agent is the `claude` CLI, so a connection is only offered here if
    // it serves the Anthropic Messages API. OpenRouter does (reached via
    // ANTHROPIC_BASE_URL); codex and ollama are OpenAI-shaped only.
    const connections: ConnectionList = {
      encryptionAvailable: true,
      connections: [
        makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true }),
        makeStatus({ provider: "openrouter", label: "OpenRouter", apiKeyConnected: true }),
        makeStatus({ provider: "codex", label: "Codex", subscriptionConnected: true }),
        makeStatus({ provider: "ollama", label: "Ollama", apiKeyConnected: true }),
      ],
    };
    await renderLoaded(connections, makeRouting());

    fireEvent.mouseDown(screen.getByLabelText(/connection/i));
    expect(screen.getByRole("option", { name: "Claude" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "OpenRouter" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Codex" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Ollama" })).toBeNull();
  });

  it("Save calls updateRouting with {agent: {connection, model}}", async () => {
    const connections: ConnectionList = {
      encryptionAvailable: true,
      connections: [makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true })],
    };
    vi.mocked(updateRouting).mockResolvedValueOnce(
      makeRouting({ agent: { connection: "claude", model: "" } }),
    );
    await renderLoaded(connections, makeRouting());

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await vi.waitFor(() => {
      expect(updateRouting).toHaveBeenCalledWith({
        agent: { connection: "claude", model: "" },
      });
    });
  });

  it("Clear calls updateRouting with {agent: null}", async () => {
    const connections: ConnectionList = {
      encryptionAvailable: true,
      connections: [makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true })],
    };
    vi.mocked(updateRouting).mockResolvedValueOnce(makeRouting());
    await renderLoaded(
      connections,
      makeRouting({ agent: { connection: "claude", model: "claude-opus-5" } }),
    );

    fireEvent.click(screen.getByRole("button", { name: /^clear$/i }));

    await vi.waitFor(() => {
      expect(updateRouting).toHaveBeenCalledWith({ agent: null });
    });
  });

  it("a getRouting failure only takes out the Model section — the rest of the page still renders", async () => {
    vi.mocked(getAgentConfig).mockResolvedValue(makeConfig());
    vi.mocked(getProfileAnswers).mockResolvedValue(makeAnswers());
    vi.mocked(getRouting).mockRejectedValue(new Error("routing unavailable"));
    vi.mocked(listConnections).mockResolvedValue({ encryptionAvailable: true, connections: [] });

    render(<MemoryRouter><AgentsPage onBack={vi.fn()} /></MemoryRouter>);

    expect(await screen.findByRole("slider", { name: "Agent autonomy" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Schedule" })).toBeTruthy();
    expect(await screen.findByText("routing unavailable")).toBeTruthy();
    expect(screen.queryByLabelText(/connection/i)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// RunNowSection
// ---------------------------------------------------------------------------

describe("AgentsPage RunNowSection", () => {
  const noConnections: ConnectionList = { encryptionAvailable: false, connections: [] };

  it("(1) idle state renders an enabled Run now button when agent is enabled", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue(makeAgentStatus({ running: false }));
    await renderLoaded(noConnections, makeRouting(), { enabled: true });

    const btn = await screen.findByRole("button", { name: /run agent now/i });
    expect(btn).toBeTruthy();
    expect(btn.hasAttribute("disabled")).toBe(false);
  });

  it("(2) clicking Run now calls triggerAgentRun and shows spinner while running:true", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue(makeAgentStatus({ running: false }));
    vi.mocked(triggerAgentRun).mockResolvedValue({ started: true, running: true });
    await renderLoaded(noConnections, makeRouting(), { enabled: true });

    const btn = await screen.findByRole("button", { name: /run agent now/i });
    await act(async () => {
      fireEvent.click(btn);
    });

    expect(triggerAgentRun).toHaveBeenCalled();
    // Button should now show running state (disabled)
    const updatedBtn = screen.getByRole("button", { name: /run agent now/i });
    expect(updatedBtn.hasAttribute("disabled")).toBe(true);
  });

  it("(3) 503 from triggerAgentRun renders the inline unreachable message", async () => {
    vi.mocked(getAgentStatus).mockResolvedValue(makeAgentStatus({ running: false }));
    vi.mocked(triggerAgentRun).mockRejectedValue(new Error("Agent service unreachable"));
    await renderLoaded(noConnections, makeRouting(), { enabled: true });

    const btn = await screen.findByRole("button", { name: /run agent now/i });
    await act(async () => {
      fireEvent.click(btn);
    });

    expect(await screen.findByText("Agent service unreachable")).toBeTruthy();
  });

  it("(4) interval is cleared after unmount (no timer leak)", async () => {
    // Set up all mocks BEFORE rendering so effects resolve correctly
    vi.mocked(getAgentConfig).mockResolvedValue(makeConfig({ enabled: true }));
    vi.mocked(getAgentStatus).mockResolvedValue(makeAgentStatus({ running: false }));
    vi.mocked(getProfileAnswers).mockResolvedValue(makeAnswers());
    vi.mocked(getRouting).mockRejectedValue(new Error("routing n/a"));
    vi.mocked(listConnections).mockResolvedValue(noConnections);

    const clearSpy = vi.spyOn(globalThis, "clearInterval");

    const { unmount } = render(<MemoryRouter><AgentsPage onBack={vi.fn()} /></MemoryRouter>);

    // Wait for the initial getAgentStatus call (and thus the setPoll setInterval) to resolve
    await screen.findByRole("button", { name: /run agent now/i });

    unmount();
    expect(clearSpy).toHaveBeenCalled();
    clearSpy.mockRestore();
  });
});
