// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  completeLogin,
  logoutConnection,
  pollLogin,
  saveConnectionKey,
  startLogin,
} from "../api/client";
import { CONNECTION_MODES } from "../api/types";
import type { ConnectionList, ConnectionStatus, PollLoginResult } from "../api/types";
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
  completeLogin: vi.fn(),
  pollLogin: vi.fn(),
  saveConnectionKey: vi.fn(),
  listConnectionModels: vi.fn(),
  testConnectionProvider: vi.fn(),
  logoutConnection: vi.fn(),
}));

function makeStatus(overrides: Partial<ConnectionStatus> = {}): ConnectionStatus {
  return {
    provider: "codex",
    label: "Codex",
    modes: ["apikey"],
    subscriptionConnected: false,
    apiKeyConnected: false,
    authMode: "apikey",
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
      makeStatus({ provider: "ollama", label: "Ollama", modes: ["url"] }),
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

    expect(await screen.findByText(/open claude sign-in/i)).toBeTruthy();
    expect(startLogin).toHaveBeenCalledWith("claude");
    expect(screen.getByLabelText(/code/i)).toBeTruthy();
  });

  it("submitting a pasted code calls completeLogin('claude', code) and fires onChanged", async () => {
    vi.mocked(startLogin).mockResolvedValueOnce({
      flow: "paste-code",
      authUrl: "https://x",
    });
    // completeLogin is the new generic function; completeClaudeLogin is an alias.
    vi.mocked(completeLogin).mockResolvedValueOnce(
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
      expect(completeLogin).toHaveBeenCalledWith("claude", "abc123#state456");
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("saving a key calls saveConnectionKey(codex, {apiKey}) and fires onChanged", async () => {
    vi.mocked(saveConnectionKey).mockResolvedValueOnce([]);
    const onChanged = vi.fn();
    const list = makeList([
      makeStatus({ provider: "codex", label: "Codex", modes: ["apikey"], authMode: "apikey" }),
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
      makeStatus({ provider: "codex", label: "Codex", modes: ["apikey"], authMode: "apikey" }),
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
        modes: ["apikey"],
        authMode: "apikey",
        apiKeyConnected: true,
      }),
    ]);
    render(<AccountsSection list={list} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: /disconnect/i }));

    await vi.waitFor(() => {
      expect(logoutConnection).toHaveBeenCalledWith("codex", "apikey");
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("ollama card: its pane gates on the url mode, not apikey", async () => {
    vi.mocked(saveConnectionKey).mockResolvedValueOnce([]);
    const onChanged = vi.fn();
    const list = makeList([
      makeStatus({ provider: "ollama", label: "Ollama", modes: ["url"], authMode: "url" }),
    ]);
    render(<AccountsSection list={list} onChanged={onChanged} />);

    fireEvent.change(screen.getByLabelText(/base url/i), {
      target: { value: "http://localhost:11434" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await vi.waitFor(() => {
      expect(saveConnectionKey).toHaveBeenCalledWith("ollama", {
        baseUrl: "http://localhost:11434",
      });
    });
    expect(onChanged).toHaveBeenCalled();
  });

  /** Flush microtasks + any zero-delay timers so React processes async state
   * updates while fake timers are active. findByText/waitFor can't be used with
   * fake timers (they poll on a real interval that never fires), so tests flush
   * explicitly then assert with synchronous queries. */
  async function flush() {    for (let i = 0; i < 6; i += 1) {
      await vi.advanceTimersByTimeAsync(0);
    }
  }

  it("codex card (device-code): clicking Connect shows user code + link, polls on interval", async () => {
    vi.useFakeTimers();
    vi.mocked(startLogin).mockResolvedValueOnce({
      flow: "device-code",
      userCode: "ABCD-EFGH",
      verificationUri: "https://auth.openai.com/codex/device",
      intervalSeconds: 5,
      expiresInSeconds: 900,
    });
    const pollResponses: PollLoginResult[] = [
      { status: "pending" },
      { status: "complete", connectedAt: Date.now() / 1000, expiresAt: Date.now() / 1000 + 3600, scope: "openid profile" },
    ];
    let pollIdx = 0;
    vi.mocked(pollLogin).mockImplementation(async () => pollResponses[pollIdx++]);
    const onChanged = vi.fn();
    const list = makeList([
      makeStatus({
        provider: "codex",
        label: "ChatGPT (OpenAI)",
        modes: ["subscription", "apikey"],
        authMode: "subscription",
      }),
    ]);
    render(<AccountsSection list={list} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: /connect/i }));
    await flush();

    // User code and link are shown
    expect(screen.getByText("ABCD-EFGH")).toBeTruthy();
    expect(screen.getByText("https://auth.openai.com/codex/device")).toBeTruthy();

    // First poll fires synchronously in startPolling (before any timer advance)
    expect(pollLogin).toHaveBeenCalledWith("codex");

    // Second poll (complete) after interval - advance to 5s
    await vi.advanceTimersByTimeAsync(5000);
    await flush();
    expect(pollLogin).toHaveBeenCalledTimes(2);
    expect(onChanged).toHaveBeenCalled();

    vi.useRealTimers();
  }, 10000);

  it("codex card (device-code): slow_down bumps interval and re-polls", async () => {
    vi.useFakeTimers();
    vi.mocked(startLogin).mockResolvedValueOnce({
      flow: "device-code",
      userCode: "SLOW",
      verificationUri: "https://auth.openai.com/codex/device",
      intervalSeconds: 5,
      expiresInSeconds: 900,
    });
    let pollCallCount = 0;
    vi.mocked(pollLogin).mockImplementation(async () => {
      pollCallCount++;
      if (pollCallCount === 1) return { status: "pending", intervalSeconds: 10 };
      return {
        status: "complete",
        connectedAt: Date.now() / 1000,
        expiresAt: Date.now() / 1000 + 3600,
        scope: "",
      };
    });
    const onChanged = vi.fn();
    const list = makeList([
      makeStatus({
        provider: "codex",
        label: "ChatGPT (OpenAI)",
        modes: ["subscription", "apikey"],
        authMode: "subscription",
      }),
    ]);
    render(<AccountsSection list={list} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: /connect/i }));
    await flush();
    expect(screen.getByText("SLOW")).toBeTruthy();

    // First poll fires immediately
    expect(pollLogin).toHaveBeenCalledTimes(1);

    // Second poll at 10s (bumped interval from slow_down)
    await vi.advanceTimersByTimeAsync(10000);
    await flush();
    expect(pollLogin).toHaveBeenCalledTimes(2);
    expect(onChanged).toHaveBeenCalled();

    vi.useRealTimers();
  }, 10000);

  it("codex card (device-code): Cancel stops polling and clears state", async () => {
    vi.useFakeTimers();
    vi.mocked(startLogin).mockResolvedValueOnce({
      flow: "device-code",
      userCode: "CANC",
      verificationUri: "https://auth.openai.com/codex/device",
      intervalSeconds: 5,
      expiresInSeconds: 900,
    });
    let pollCallCount = 0;
    vi.mocked(pollLogin).mockImplementation(async () => {
      pollCallCount++;
      return { status: "pending" };
    });
    const onChanged = vi.fn();
    const list = makeList([
      makeStatus({
        provider: "codex",
        label: "ChatGPT (OpenAI)",
        modes: ["subscription", "apikey"],
        authMode: "subscription",
      }),
    ]);
    render(<AccountsSection list={list} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: /connect/i }));
    await flush();
    expect(screen.getByText("CANC")).toBeTruthy();

    // Initial poll fires synchronously in startPolling
    const initialCalls = pollCallCount;

    // Click Cancel
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    // Advance timers - no more polls should fire after cancel
    await vi.advanceTimersByTimeAsync(5000);
    await flush();
    // PollLogin should not have been called again after cancel
    expect(pollCallCount).toBe(initialCalls);

    vi.useRealTimers();
  }, 10000);

  it("codex card (device-code): unmount cancels polling (no leak)", async () => {
    // Must use fake timers for the entire test
    vi.useFakeTimers();
    vi.mocked(startLogin).mockResolvedValueOnce({
      flow: "device-code",
      userCode: "LEAK",
      verificationUri: "https://auth.openai.com/codex/device",
      intervalSeconds: 5,
      expiresInSeconds: 900,
    });
    let pollCallCount = 0;
    vi.mocked(pollLogin).mockImplementation(async () => {
      pollCallCount++;
      return { status: "pending" };
    });
    const onChanged = vi.fn();
    const list = makeList([
      makeStatus({
        provider: "codex",
        label: "ChatGPT (OpenAI)",
        modes: ["subscription", "apikey"],
        authMode: "subscription",
      }),
    ]);
    const { unmount } = render(<AccountsSection list={list} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: /connect/i }));
    await flush();
    expect(screen.getByText("LEAK")).toBeTruthy();

    // Initial poll fires synchronously in startPolling
    const initialCalls = pollCallCount;

    // Unmount the component — timer should be cleaned up
    unmount();

    // Advance time — no poll should fire after unmount
    await vi.advanceTimersByTimeAsync(5000);
    await flush();
    // PollLogin should not have been called again after unmount
    expect(pollCallCount).toBe(initialCalls);

    vi.useRealTimers();
  }, 10000);

  it("CONNECTION_MODES pins the three backend mode literals fixtures derive from", () => {
    expect(CONNECTION_MODES).toEqual(["subscription", "apikey", "url"]);
  });
});
