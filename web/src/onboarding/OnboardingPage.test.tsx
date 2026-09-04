// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  extractTruth,
  getOnboarding,
  getProfile,
  getRouting,
  getTruth,
  listConnections,
  saveTruth,
  updateOnboarding,
} from "../api/client";
import type { ConnectionList, OnboardingState, Routing, TruthDoc } from "../api/types";
import { WizardProvider } from "../wizard/store";
import { OnboardingPage } from "./OnboardingPage";

vi.mock("../api/client", () => ({
  extractTruth: vi.fn(),
  getOnboarding: vi.fn(),
  getProfile: vi.fn(),
  getRouting: vi.fn(),
  getTruth: vi.fn(),
  listConnections: vi.fn(),
  saveTruth: vi.fn(),
  updateOnboarding: vi.fn(),
  uploadCv: vi.fn(),
  // Touched only by interactions in the provider step's sub-sections; stubbed
  // so their modules import cleanly under the mocked client.
  listConnectionModels: vi.fn(),
  testConnectionProvider: vi.fn(),
  updateRouting: vi.fn(),
  completeClaudeLogin: vi.fn(),
  logoutConnection: vi.fn(),
  saveConnectionKey: vi.fn(),
  startLogin: vi.fn(),
}));

function emptyTruth(): TruthDoc {
  return {
    experiences: [],
    education: [],
    skills: [],
    hobbies: [],
    profile: { name: "", email: "", phone: "", location: "", links: [], summary: "" },
  };
}

function emptyConnections(): ConnectionList {
  return { encryptionAvailable: true, connections: [] };
}

function routing(withDefault: boolean): Routing {
  return {
    tasks: {},
    agent: null,
    default: withDefault ? { connection: "claude", model: "claude-sonnet" } : null,
  };
}

function onboarding(partial: Partial<OnboardingState>): OnboardingState {
  return {
    providerDone: false,
    hasProfile: false,
    cvReviewedAt: null,
    tourSeenAt: null,
    complete: false,
    ...partial,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderPage(onComplete = vi.fn()) {
  return render(
    <WizardProvider>
      <OnboardingPage onComplete={onComplete} />
    </WizardProvider>,
  );
}

describe("OnboardingPage", () => {
  it("opens on Connect a provider when no provider is connected", async () => {
    vi.mocked(listConnections).mockResolvedValue(emptyConnections());
    vi.mocked(getRouting).mockResolvedValue(routing(false));
    vi.mocked(getOnboarding).mockResolvedValue(
      onboarding({ providerDone: false, hasProfile: false }),
    );
    vi.mocked(getProfile).mockResolvedValue({ hasProfile: false });

    renderPage();

    expect(await screen.findByText("Connect a provider")).toBeTruthy();
  });

  it("skips the provider step and opens on Upload when a default is set but the CV isn't reviewed", async () => {
    vi.mocked(listConnections).mockResolvedValue(emptyConnections());
    vi.mocked(getRouting).mockResolvedValue(routing(true));
    vi.mocked(getOnboarding).mockResolvedValue(
      onboarding({ providerDone: true, hasProfile: false, cvReviewedAt: null }),
    );
    vi.mocked(getProfile).mockResolvedValue({ hasProfile: false });

    renderPage();

    expect(await screen.findByText("Drop your CV here")).toBeTruthy();
  });

  it("skips Upload and opens on Review when a profile already exists and the CV isn't reviewed", async () => {
    vi.mocked(listConnections).mockResolvedValue(emptyConnections());
    vi.mocked(getRouting).mockResolvedValue(routing(true));
    vi.mocked(getOnboarding).mockResolvedValue(
      onboarding({ providerDone: true, hasProfile: true, cvReviewedAt: null }),
    );
    vi.mocked(getProfile).mockResolvedValue({ hasProfile: true });
    vi.mocked(getTruth).mockResolvedValue(emptyTruth());
    vi.mocked(extractTruth).mockResolvedValue(emptyTruth());
    vi.mocked(saveTruth).mockResolvedValue(undefined);
    vi.mocked(updateOnboarding).mockResolvedValue(
      onboarding({ providerDone: true, hasProfile: true }),
    );

    renderPage();

    expect(await screen.findByText("Review what we found")).toBeTruthy();
  });
});
