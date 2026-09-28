// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import {
  getAgentConfig,
  getJobBoardKey,
  getSigninQueue,
  saveJobBoardKey,
  testJobBoardKey,
  updateAgentConfig,
} from "../api/client";
import type { AgentConfig, JobBoard } from "../api/types";
import { JobBoardsPage } from "./JobBoardsPage";

vi.mock("../api/client", () => ({
  getAgentConfig: vi.fn(),
  getJobBoardKey: vi.fn(),
  getSigninQueue: vi.fn(),
  saveJobBoardKey: vi.fn(),
  testJobBoardKey: vi.fn(),
  updateAgentConfig: vi.fn(),
}));

const REMOTE_ROCKETSHIP: JobBoard = {
  source: "remoterocketship",
  signinUrl: "",
  enabled: true,
  mode: "feed",
  modeLocked: true,
  domain: "remoterocketship.com",
  effectiveSigninUrl: "",
  isDefault: false,
  isApi: true,
  keyRequired: true,
  searchUrl: "",
};

const ARBEITNOW: JobBoard = {
  source: "arbeitnow",
  signinUrl: "",
  mode: "feed",
  modeLocked: true,
  domain: "arbeitnow.com",
  effectiveSigninUrl: "",
  isDefault: true,
  isApi: true,
  keyRequired: false,
  searchUrl: "",
  postingUrlPattern: "",
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const DEFAULT_BOARDS: JobBoard[] = [
  { source: "ashby", signinUrl: "", enabled: true, mode: "dork", modeLocked: true, domain: "jobs.ashbyhq.com", effectiveSigninUrl: "https://jobs.ashbyhq.com", isDefault: true, isApi: false, keyRequired: false, searchUrl: "", postingUrlPattern: "" },
  { source: "greenhouse", signinUrl: "", enabled: true, mode: "dork", modeLocked: true, domain: "job-boards.greenhouse.io", effectiveSigninUrl: "https://job-boards.greenhouse.io", isDefault: true, isApi: false, keyRequired: false, searchUrl: "", postingUrlPattern: "" },
  { source: "lever", signinUrl: "", enabled: true, mode: "dork", modeLocked: true, domain: "jobs.lever.co", effectiveSigninUrl: "https://jobs.lever.co", isDefault: true, isApi: false, keyRequired: false, searchUrl: "", postingUrlPattern: "" },
  { source: "workday", signinUrl: "", enabled: true, mode: "dork", modeLocked: true, domain: "myworkdayjobs.com", effectiveSigninUrl: "https://www.myworkdayjobs.com", isDefault: true, isApi: false, keyRequired: false, searchUrl: "", postingUrlPattern: "" },
];

function makeConfig(jobBoards: JobBoard[]): AgentConfig {
  return {
    mode: "full",
    enabled: true,
    blockedCompanies: [],
    runAt: ["09:00"],
    runDays: ["mon"],
    runTimezone: "UTC",
    profiles: [],
    jobBoards,
    targetCompanies: [],
    cooldownDays: null,
    cooldownDaysSameRole: null,
    cooldownDaysSameCompany: null,
    maxApplicationsPerRun: null,
    maxPostingAgeDays: null,
    companyBoards: [],
  };
}

async function renderPage(config: AgentConfig) {
  vi.mocked(getAgentConfig).mockResolvedValue(config);
  render(
    <MemoryRouter>
      <JobBoardsPage />
    </MemoryRouter>,
  );
  // Wait for the loaded page instead of the loading placeholder.
  await screen.findByText("Job boards");
}

describe("JobBoardsPage", () => {
  it("renders a Sign in button for each default board when the queue is empty", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    await renderPage(makeConfig(DEFAULT_BOARDS));

    await screen.findByText("No sites are waiting on a sign-in.");
    const signInButtons = screen.getAllByRole("button", { name: "Sign in" });
    expect(signInButtons).toHaveLength(4);
  });

  it("shows a Default chip and no remove button for a default board", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    await renderPage(makeConfig([DEFAULT_BOARDS[0]]));

    await screen.findByText("Default");
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
  });

  it("shows a Default chip and no Remove, Sign in or API key controls for a keyless API board", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    await renderPage(makeConfig([ARBEITNOW]));

    await screen.findByText("Default");
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sign in" })).toBeNull();
    expect(screen.queryByLabelText("API key")).toBeNull();
    expect(getJobBoardKey).not.toHaveBeenCalled();
  });

  it("shows a remove button for a non-default board and removes it", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const linkedin: JobBoard = {
      source: "linkedin",
      signinUrl: "",
      enabled: true,
      mode: "dork",
      modeLocked: true,
      domain: "linkedin.com/jobs",
      effectiveSigninUrl: "https://www.linkedin.com/login",
      isDefault: false,
      isApi: false,
      keyRequired: false,
      searchUrl: "",
      postingUrlPattern: "",
    };
    const config = makeConfig([...DEFAULT_BOARDS, linkedin]);
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig(DEFAULT_BOARDS));
    await renderPage(config);

    const removeButton = await screen.findByRole("button", { name: "Remove" });
    fireEvent.click(removeButton);

    await waitFor(() => expect(updateAgentConfig).toHaveBeenCalledWith({ jobBoards: DEFAULT_BOARDS }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Remove" })).toBeNull());
  });

  it("disables the Sign in button when effectiveSigninUrl is empty", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const board: JobBoard = {
      source: "custom.example.com",
      signinUrl: "",
      enabled: true,
      mode: "direct",
      modeLocked: false,
      domain: "custom.example.com",
      effectiveSigninUrl: "",
      isDefault: false,
      isApi: false,
      keyRequired: false,
      searchUrl: "",
      postingUrlPattern: "",
    };
    await renderPage(makeConfig([board]));

    const button = await screen.findByRole("button", { name: "Sign in" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("adds a known board via the add control", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig(DEFAULT_BOARDS));
    await renderPage(makeConfig(DEFAULT_BOARDS));

    await screen.findByText("No sites are waiting on a sign-in.");
    fireEvent.mouseDown(screen.getByRole("combobox"));
    fireEvent.click(within(screen.getByRole("listbox")).getByText("linkedin"));
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(updateAgentConfig).toHaveBeenCalledWith({
        jobBoards: [
          ...DEFAULT_BOARDS,
          {
            source: "linkedin",
            signinUrl: "",
            enabled: true,
            mode: "dork",
            modeLocked: true,
            domain: "",
            effectiveSigninUrl: "",
            isDefault: false,
            isApi: false,
            keyRequired: false,
            searchUrl: "",
            postingUrlPattern: "",
          },
        ],
      }),
    );
  });

  it("adds a custom domain via the add control", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig(DEFAULT_BOARDS));
    await renderPage(makeConfig(DEFAULT_BOARDS));

    await screen.findByText("No sites are waiting on a sign-in.");
    fireEvent.mouseDown(screen.getByRole("combobox"));
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Custom domain…"));
    fireEvent.change(screen.getByLabelText("Domain"), { target: { value: "custom.example.com" } });
    fireEvent.change(screen.getByLabelText("Search URL template (optional)"), {
      target: { value: "https://custom.example.com/jobs?q={keywords}" },
    });
    fireEvent.change(screen.getByLabelText("Posting link pattern (optional)"), {
      target: { value: "https://custom.example.com/jobs/*" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(updateAgentConfig).toHaveBeenCalledWith({
        jobBoards: [
          ...DEFAULT_BOARDS,
          {
            source: "custom.example.com",
            signinUrl: "",
            enabled: true,
            mode: "direct",
            modeLocked: false,
            domain: "custom.example.com",
            effectiveSigninUrl: "",
            isDefault: false,
            isApi: false,
            keyRequired: false,
            searchUrl: "https://custom.example.com/jobs?q={keywords}",
            postingUrlPattern: "https://custom.example.com/jobs/*",
          },
        ],
      }),
    );
  });

  it("rejects a custom posting link pattern that doesn't start with http(s)://", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    await renderPage(makeConfig(DEFAULT_BOARDS));

    await screen.findByText("No sites are waiting on a sign-in.");
    fireEvent.mouseDown(screen.getByRole("combobox"));
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Custom domain…"));
    fireEvent.change(screen.getByLabelText("Domain"), { target: { value: "custom.example.com" } });
    fireEvent.change(screen.getByLabelText("Posting link pattern (optional)"), {
      target: { value: "custom.example.com/jobs/*" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await screen.findByText("Must start with http:// or https://");
    expect(updateAgentConfig).not.toHaveBeenCalled();
  });

  it("saves an API key and clears the field", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    vi.mocked(getJobBoardKey).mockResolvedValue({
      source: "remoterocketship",
      keySet: false,
      encryptionAvailable: true,
    });
    vi.mocked(saveJobBoardKey).mockResolvedValue({
      source: "remoterocketship",
      keySet: true,
      encryptionAvailable: true,
    });
    await renderPage(makeConfig([REMOTE_ROCKETSHIP]));

    const field = await screen.findByLabelText("API key");
    fireEvent.change(field, { target: { value: "rr_secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));

    await waitFor(() =>
      expect(saveJobBoardKey).toHaveBeenCalledWith("remoterocketship", "rr_secret"),
    );
    // The field is emptied after a save: the key is write-only, and leaving
    // it on screen would imply it can be read back.
    await waitFor(() => expect((field as HTMLInputElement).value).toBe(""));
  });

  it("surfaces a failed key test as an error", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    vi.mocked(getJobBoardKey).mockResolvedValue({
      source: "remoterocketship",
      keySet: true,
      encryptionAvailable: true,
    });
    vi.mocked(testJobBoardKey).mockResolvedValue({ ok: false, detail: "Invalid API key" });
    await renderPage(makeConfig([REMOTE_ROCKETSHIP]));

    fireEvent.click(await screen.findByRole("button", { name: "Test" }));
    await screen.findByText("Invalid API key");
  });

  it("shows an error when the config fails to load", async () => {
    vi.mocked(getAgentConfig).mockRejectedValue(new Error("boom"));
    render(
      <MemoryRouter>
        <JobBoardsPage />
      </MemoryRouter>,
    );
    await screen.findByText("boom");
  });

  // --- Board mode: dork | direct --------------------------------------------

  it("renders a working mode selector for a custom board and saves a change", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const custom: JobBoard = {
      source: "custom.example.com",
      signinUrl: "",
      enabled: true,
      mode: "dork",
      modeLocked: false,
      domain: "custom.example.com",
      effectiveSigninUrl: "",
      isDefault: false,
      isApi: false,
      keyRequired: false,
      searchUrl: "",
      postingUrlPattern: "",
    };
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig([custom]));
    await renderPage(makeConfig([custom]));

    const select = await screen.findByRole("combobox", { name: "Mode" });
    fireEvent.mouseDown(select);
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Search the site directly"));

    await waitFor(() =>
      expect(updateAgentConfig).toHaveBeenCalledWith({
        jobBoards: [{ ...custom, mode: "direct" }],
      }),
    );
  });

  it("renders no mode selector for a catalog (mode-locked) board", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    await renderPage(makeConfig([DEFAULT_BOARDS[0]]));

    await screen.findByText("Searched via Google.");
    expect(screen.queryByText("Google dork")).toBeNull();
    expect(screen.queryByText("Search the site directly")).toBeNull();
  });

  it("renders the API-key affordance and no mode selector for a feed board", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    vi.mocked(getJobBoardKey).mockResolvedValue({
      source: "remoterocketship",
      keySet: false,
      encryptionAvailable: true,
    });
    await renderPage(makeConfig([REMOTE_ROCKETSHIP]));

    await screen.findByLabelText("API key");
    await screen.findByText("Postings come from this board's own API — only the API key below is configurable.");
    expect(screen.queryByText("Google dork")).toBeNull();
    expect(screen.queryByText("Search the site directly")).toBeNull();
  });

  // --- Edit dialog ------------------------------------------------------

  it("edits a default board's sign-in URL and persists it", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const board = DEFAULT_BOARDS[0];
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig(DEFAULT_BOARDS));
    await renderPage(makeConfig([board]));

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(await screen.findByLabelText("Sign-in URL"), {
      target: { value: "https://jobs.ashbyhq.com/login" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(updateAgentConfig).toHaveBeenCalledWith({
        jobBoards: [{ ...board, signinUrl: "https://jobs.ashbyhq.com/login" }],
      }),
    );
  });

  it("edits a custom board's search URL and persists it", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const board: JobBoard = {
      source: "custom.example.com",
      signinUrl: "",
      enabled: true,
      mode: "direct",
      modeLocked: false,
      domain: "custom.example.com",
      effectiveSigninUrl: "",
      isDefault: false,
      isApi: false,
      keyRequired: false,
      searchUrl: "",
      postingUrlPattern: "",
    };
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig([board]));
    await renderPage(makeConfig([board]));

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(await screen.findByLabelText("Search URL template"), {
      target: { value: "https://custom.example.com/jobs?q={keywords}&loc={location}" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(updateAgentConfig).toHaveBeenCalledWith({
        jobBoards: [
          { ...board, searchUrl: "https://custom.example.com/jobs?q={keywords}&loc={location}" },
        ],
      }),
    );
  });

  it("edits a custom board's posting link pattern and persists it", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const board: JobBoard = {
      source: "custom.example.com",
      signinUrl: "",
      mode: "direct",
      modeLocked: false,
      domain: "custom.example.com",
      effectiveSigninUrl: "",
      isDefault: false,
      isApi: false,
      searchUrl: "",
      postingUrlPattern: "",
    };
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig([board]));
    await renderPage(makeConfig([board]));

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(await screen.findByLabelText("Posting link pattern (optional)"), {
      target: { value: "https://custom.example.com/jobs/*" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(updateAgentConfig).toHaveBeenCalledWith({
        jobBoards: [{ ...board, postingUrlPattern: "https://custom.example.com/jobs/*" }],
      }),
    );
  });

  it("hides the posting link pattern field in dork mode", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const board: JobBoard = {
      source: "custom.example.com",
      signinUrl: "",
      mode: "dork",
      modeLocked: false,
      domain: "custom.example.com",
      effectiveSigninUrl: "",
      isDefault: false,
      isApi: false,
      searchUrl: "",
      postingUrlPattern: "",
    };
    await renderPage(makeConfig([board]));

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await screen.findByLabelText("Sign-in URL");
    expect(screen.queryByLabelText("Posting link pattern (optional)")).toBeNull();
  });

  it("preserves an existing posting link pattern when editing an unrelated field", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const board: JobBoard = {
      source: "custom.example.com",
      signinUrl: "",
      mode: "direct",
      modeLocked: false,
      domain: "custom.example.com",
      effectiveSigninUrl: "",
      isDefault: false,
      isApi: false,
      searchUrl: "",
      postingUrlPattern: "https://custom.example.com/jobs/*",
    };
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig([board]));
    await renderPage(makeConfig([board]));

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(await screen.findByLabelText("Sign-in URL"), {
      target: { value: "https://custom.example.com/login" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(updateAgentConfig).toHaveBeenCalledWith({
        jobBoards: [{ ...board, signinUrl: "https://custom.example.com/login" }],
      }),
    );
  });

  it("allows editing the posting link pattern of a default/catalog direct-mode board", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const board: JobBoard = { ...DEFAULT_BOARDS[0], mode: "direct" };
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig([board]));
    await renderPage(makeConfig([board]));

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(await screen.findByLabelText("Posting link pattern (optional)"), {
      target: { value: "https://jobs.ashbyhq.com/*" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(updateAgentConfig).toHaveBeenCalledWith({
        jobBoards: [{ ...board, postingUrlPattern: "https://jobs.ashbyhq.com/*" }],
      }),
    );
  });

  it("clears a stale search URL when saving a dork-mode custom board", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const board: JobBoard = {
      source: "custom.example.com",
      signinUrl: "",
      enabled: true,
      mode: "dork",
      modeLocked: false,
      domain: "custom.example.com",
      effectiveSigninUrl: "",
      isDefault: false,
      isApi: false,
      keyRequired: false,
      searchUrl: "https://custom.example.com/jobs?q={keywords}",
      postingUrlPattern: "",
    };
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig([board]));
    await renderPage(makeConfig([board]));

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(await screen.findByLabelText("Sign-in URL"), {
      target: { value: "https://custom.example.com/login" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(updateAgentConfig).toHaveBeenCalledWith({
        jobBoards: [{ ...board, signinUrl: "https://custom.example.com/login", searchUrl: "" }],
      }),
    );
  });

  it("clears a custom board's search URL and posting pattern when its mode is switched away from direct", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const board: JobBoard = {
      source: "custom.example.com",
      signinUrl: "",
      enabled: true,
      mode: "direct",
      modeLocked: false,
      domain: "custom.example.com",
      effectiveSigninUrl: "",
      isDefault: false,
      isApi: false,
      keyRequired: false,
      searchUrl: "https://custom.example.com/jobs?q={keywords}",
      postingUrlPattern: "https://custom.example.com/jobs/*",
    };
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig([board]));
    await renderPage(makeConfig([board]));

    const select = await screen.findByRole("combobox", { name: "Mode" });
    fireEvent.mouseDown(select);
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Google dork"));

    await waitFor(() =>
      expect(updateAgentConfig).toHaveBeenCalledWith({
        jobBoards: [{ ...board, mode: "dork", searchUrl: "", postingUrlPattern: "" }],
      }),
    );
  });

  it("refuses a source rename that collides, casefolded, with a ß/ss variant of another board", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const custom: JobBoard = {
      source: "strasse.de",
      signinUrl: "",
      enabled: true,
      mode: "direct",
      modeLocked: false,
      domain: "strasse.de",
      effectiveSigninUrl: "",
      isDefault: false,
      isApi: false,
      keyRequired: false,
      searchUrl: "",
      postingUrlPattern: "",
    };
    const other: JobBoard = { ...custom, source: "other.example.com", domain: "other.example.com" };
    await renderPage(makeConfig([custom, other]));

    const editButtons = await screen.findAllByRole("button", { name: "Edit" });
    fireEvent.click(editButtons[1]);
    fireEvent.change(await screen.findByLabelText("Source"), {
      target: { value: "straße.de" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await screen.findByText("Another board already uses this source.");
    expect(updateAgentConfig).not.toHaveBeenCalled();
  });

  it("refuses a source rename that collides with another board, without saving", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const custom: JobBoard = {
      source: "custom.example.com",
      signinUrl: "",
      enabled: true,
      mode: "direct",
      modeLocked: false,
      domain: "custom.example.com",
      effectiveSigninUrl: "",
      isDefault: false,
      isApi: false,
      keyRequired: false,
      searchUrl: "",
      postingUrlPattern: "",
    };
    const other: JobBoard = { ...custom, source: "other.example.com", domain: "other.example.com" };
    await renderPage(makeConfig([custom, other]));

    const editButtons = await screen.findAllByRole("button", { name: "Edit" });
    fireEvent.click(editButtons[0]);
    fireEvent.change(await screen.findByLabelText("Source"), {
      target: { value: "  Other.Example.com  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await screen.findByText("Another board already uses this source.");
    expect(updateAgentConfig).not.toHaveBeenCalled();
  });

  // --- Enabled toggle -----------------------------------------------------

  it("toggling a default board off calls updateAgentConfig with that board's enabled false", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const board = DEFAULT_BOARDS[0];
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig([{ ...board, enabled: false }]));
    await renderPage(makeConfig([board]));

    const toggle = await screen.findByRole("switch", { name: `Search ${board.domain}` });
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(updateAgentConfig).toHaveBeenCalledWith({
        jobBoards: [{ ...board, enabled: false }],
      }),
    );
  });

  it("renders a disabled board's switch unchecked and still shows no Remove button", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const board = { ...DEFAULT_BOARDS[0], enabled: false };
    await renderPage(makeConfig([board]));

    const toggle = await screen.findByRole("switch", { name: `Search ${board.domain}` });
    expect((toggle as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
  });
});
