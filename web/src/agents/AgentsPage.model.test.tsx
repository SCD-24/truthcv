// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  getAgentConfig,
  getProfileAnswers,
  getRouting,
  listConnectionModels,
  listConnections,
  listScreenings,
  updateRouting,
} from "../api/client";
import type { AgentConfig, ConnectionList, ConnectionStatus, ProfileAnswers, Routing } from "../api/types";
import { AgentsPage } from "./AgentsPage";

/** Mirrors AccountsSection.test.tsx's boundary choice — mock the API client
 * module directly and render with @testing-library/react + jsdom. */
vi.mock("../api/client", () => ({
  getAgentConfig: vi.fn(),
  getProfileAnswers: vi.fn(),
  listScreenings: vi.fn(),
  getRouting: vi.fn(),
  listConnections: vi.fn(),
  listConnectionModels: vi.fn(),
  updateAgentConfig: vi.fn(),
  saveProfileAnswers: vi.fn(),
  deleteScreening: vi.fn(),
  updateRouting: vi.fn(),
}));

function makeConfig(overrides: Partial<AgentConfig> = {}): AgentConfig {
  return {
    enabled: true,
    blockedCompanies: [],
    runAt: ["09:00"],
    runDays: ["mon"],
    profiles: [],
    targetCompanies: [],
    cooldownDays: null,
    maxApplicationsPerRun: null,
    companyBoards: [],
    ...overrides,
  };
}

function makeAnswers(): ProfileAnswers {
  return {
    phone: "",
    workAuthorisation: "",
    salaryExpectation: "",
    noticePeriod: "",
    locationPreference: "",
    canonicalCvAssetId: null,
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

async function renderLoaded(connections: ConnectionList, routing: Routing) {
  vi.mocked(getAgentConfig).mockResolvedValue(makeConfig());
  vi.mocked(getProfileAnswers).mockResolvedValue(makeAnswers());
  vi.mocked(listScreenings).mockResolvedValue([]);
  vi.mocked(getRouting).mockResolvedValue(routing);
  vi.mocked(listConnections).mockResolvedValue(connections);
  vi.mocked(listConnectionModels).mockResolvedValue([]);
  render(<AgentsPage onBack={vi.fn()} />);
  await screen.findByRole("heading", { name: "Model" });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AgentsPage model section", () => {
  it("lists only claude among mixed connections", async () => {
    const connections: ConnectionList = {
      encryptionAvailable: true,
      connections: [
        makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true }),
        makeStatus({ provider: "codex", label: "Codex", subscriptionConnected: true }),
      ],
    };
    await renderLoaded(connections, makeRouting());

    fireEvent.mouseDown(screen.getByLabelText(/connection/i));
    expect(screen.getByRole("option", { name: "Claude" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Codex" })).toBeNull();
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
    vi.mocked(listScreenings).mockResolvedValue([]);
    vi.mocked(getRouting).mockRejectedValue(new Error("routing unavailable"));
    vi.mocked(listConnections).mockResolvedValue({ encryptionAvailable: true, connections: [] });

    render(<AgentsPage onBack={vi.fn()} />);

    expect(await screen.findByLabelText("Agent enabled")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Schedule" })).toBeTruthy();
    expect(await screen.findByText("routing unavailable")).toBeTruthy();
    expect(screen.queryByLabelText(/connection/i)).toBeNull();
  });
});
