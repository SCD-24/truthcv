// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { getAgentConfig, getSigninQueue, updateAgentConfig } from "../api/client";
import type { AgentConfig, JobBoard } from "../api/types";
import { JobBoardsPage } from "./JobBoardsPage";

vi.mock("../api/client", () => ({
  getAgentConfig: vi.fn(),
  getSigninQueue: vi.fn(),
  updateAgentConfig: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const DEFAULT_BOARDS: JobBoard[] = [
  { source: "ashby", signinUrl: "", domain: "jobs.ashbyhq.com", effectiveSigninUrl: "https://jobs.ashbyhq.com", isDefault: true },
  { source: "greenhouse", signinUrl: "", domain: "job-boards.greenhouse.io", effectiveSigninUrl: "https://job-boards.greenhouse.io", isDefault: true },
  { source: "lever", signinUrl: "", domain: "jobs.lever.co", effectiveSigninUrl: "https://jobs.lever.co", isDefault: true },
  { source: "workday", signinUrl: "", domain: "myworkdayjobs.com", effectiveSigninUrl: "https://www.myworkdayjobs.com", isDefault: true },
];

function makeConfig(jobBoards: JobBoard[]): AgentConfig {
  return {
    mode: "full",
    enabled: true,
    blockedCompanies: [],
    runAt: ["09:00"],
    runDays: ["mon"],
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

  it("shows a remove button for a non-default board and removes it", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({ sites: [] });
    const linkedin: JobBoard = {
      source: "linkedin",
      signinUrl: "",
      domain: "linkedin.com/jobs",
      effectiveSigninUrl: "https://www.linkedin.com/login",
      isDefault: false,
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
      domain: "custom.example.com",
      effectiveSigninUrl: "",
      isDefault: false,
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
          { source: "linkedin", signinUrl: "", domain: "", effectiveSigninUrl: "", isDefault: false },
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
    fireEvent.change(screen.getByLabelText("Sign-in URL (optional)"), {
      target: { value: "https://custom.example.com/login" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(updateAgentConfig).toHaveBeenCalledWith({
        jobBoards: [
          ...DEFAULT_BOARDS,
          {
            source: "custom.example.com",
            signinUrl: "https://custom.example.com/login",
            domain: "custom.example.com",
            effectiveSigninUrl: "https://custom.example.com/login",
            isDefault: false,
          },
        ],
      }),
    );
  });

  it("renders a queue entry with its waiting count and navigates to the browser session path", async () => {
    vi.mocked(getSigninQueue).mockResolvedValue({
      sites: [
        {
          host: "jobs.ashbyhq.com",
          waiting: 3,
          companies: ["Acme"],
          lastBlockedAt: "",
          signinUrl: "https://jobs.ashbyhq.com",
        },
      ],
    });
    await renderPage(makeConfig(DEFAULT_BOARDS));

    await screen.findByText(/3 postings waiting/);
    expect(screen.getByText(/Acme/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign in to jobs.ashbyhq.com" })).toBeTruthy();
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
});
