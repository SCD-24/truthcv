// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  completeClaudeLogin,
  logoutConnection,
  saveConnectionKey,
  startLogin,
} from "../api/client";
import type { ConnectionList, ConnectionStatus } from "../api/types";
import { AccountsSection } from "./AccountsSection";

/**
 * Mirrors SettingsModal.test.tsx's boundary choice — mock the API client
 * module directly rather than stubbing fetch, since AccountsSection is
 * rendered here (unlike SettingsModal, which that file left unrendered for
 * lack of a DOM environment). This file adds @testing-library/react + jsdom,
 * scoped to just this test via the environment docblock above, so the rest
 * of the suite keeps running under the lighter "node" environment.
 */
vi.mock("../api/client", () => ({
  startLogin: vi.fn(),
  completeClaudeLogin: vi.fn(),
  saveConnectionKey: vi.fn(),
  listConnectionModels: vi.fn(),
  testConnectionProvider: vi.fn(),
  logoutConnection: vi.fn(),
}));

function makeStatus(overrides: Partial<ConnectionStatus> = {}): ConnectionStatus {
  return {
    provider: "codex",
    label: "Codex",
    modes: ["apiKey"],
    subscriptionConnected: false,
    apiKeyConnected: false,
    authMode: "apiKey",
    expiresAt: null,
    connectedAt: null,
    ...overrides,
  };
}

function makeList(connections: ConnectionStatus[]): ConnectionList {
  return { encryptionAvailable: true, connections };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AccountsSection", () => {
  it("renders one card per connection with its label", () => {
    const list = makeList([
      makeStatus({ provider: "claude", label: "Claude" }),
      makeStatus({ provider: "codex", label: "Codex" }),
      makeStatus({ provider: "ollama", label: "Ollama" }),
    ]);
    render(<AccountsSection list={list} onChanged={vi.fn()} />);

    expect(screen.getByText("Claude")).toBeTruthy();
    expect(screen.getByText("Codex")).toBeTruthy();
    expect(screen.getByText("Ollama")).toBeTruthy();
  });

  it("claude card: clicking Connect calls startLogin and shows the paste field", async () => {
    vi.mocked(startLogin).mockResolvedValueOnce({
      flow: "paste-code",
      authUrl: "https://x",
    });
    const list = makeList([
      makeStatus({
        provider: "claude",
        label: "Claude",
        modes: ["subscription"],
        authMode: "subscription",
      }),
    ]);
    render(<AccountsSection list={list} onChanged={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /connect/i }));

    expect(await screen.findByText(/open anthropic sign-in/i)).toBeTruthy();
    expect(startLogin).toHaveBeenCalledWith("claude");
    expect(screen.getByLabelText(/code/i)).toBeTruthy();
  });

  it("submitting a pasted code calls completeClaudeLogin and fires onChanged", async () => {
    vi.mocked(startLogin).mockResolvedValueOnce({
      flow: "paste-code",
      authUrl: "https://x",
    });
    vi.mocked(completeClaudeLogin).mockResolvedValueOnce(
      makeStatus({ provider: "claude", label: "Claude", subscriptionConnected: true }),
    );
    const onChanged = vi.fn();
    const list = makeList([
      makeStatus({
        provider: "claude",
        label: "Claude",
        modes: ["subscription"],
        authMode: "subscription",
      }),
    ]);
    render(<AccountsSection list={list} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: /connect/i }));
    await screen.findByLabelText(/code/i);
    fireEvent.change(screen.getByLabelText(/code/i), {
      target: { value: "abc123#state456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    await vi.waitFor(() => {
      expect(completeClaudeLogin).toHaveBeenCalledWith("abc123#state456");
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("saving a key calls saveConnectionKey(codex, {apiKey}) and fires onChanged", async () => {
    vi.mocked(saveConnectionKey).mockResolvedValueOnce([]);
    const onChanged = vi.fn();
    const list = makeList([
      makeStatus({ provider: "codex", label: "Codex", modes: ["apiKey"], authMode: "apiKey" }),
    ]);
    render(<AccountsSection list={list} onChanged={onChanged} />);

    fireEvent.change(screen.getByLabelText(/api key/i), { target: { value: "sk-x" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await vi.waitFor(() => {
      expect(saveConnectionKey).toHaveBeenCalledWith("codex", { apiKey: "sk-x" });
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("a rejected saveConnectionKey renders its message in an Alert", async () => {
    vi.mocked(saveConnectionKey).mockRejectedValueOnce(new Error("Bad key format."));
    const list = makeList([
      makeStatus({ provider: "codex", label: "Codex", modes: ["apiKey"], authMode: "apiKey" }),
    ]);
    render(<AccountsSection list={list} onChanged={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/api key/i), { target: { value: "sk-x" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByText("Bad key format.")).toBeTruthy();
  });

  it("disconnect button calls logoutConnection with the card's mode", async () => {
    vi.mocked(logoutConnection).mockResolvedValueOnce(makeStatus({ provider: "codex" }));
    const onChanged = vi.fn();
    const list = makeList([
      makeStatus({
        provider: "codex",
        label: "Codex",
        modes: ["apiKey"],
        authMode: "apiKey",
        apiKeyConnected: true,
      }),
    ]);
    render(<AccountsSection list={list} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: /disconnect/i }));

    await vi.waitFor(() => {
      expect(logoutConnection).toHaveBeenCalledWith("codex", "apiKey");
    });
    expect(onChanged).toHaveBeenCalled();
  });
});
