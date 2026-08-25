// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  getAgentConfig,
  getProfileAnswers,
  getRouting,
  listConnectionModels,
  listConnections,
  saveProfileAnswers,
  updateAgentConfig,
} from "../api/client";
import type { AgentConfig, ConnectionList, JobProfile, ProfileAnswers, Routing } from "../api/types";
import { AgentsPage } from "./AgentsPage";

/** Mirrors AgentsPage.model.test.tsx's boundary choice — mock the API client
 * module directly and render with @testing-library/react + jsdom. */
vi.mock("../api/client", () => ({
  getAgentConfig: vi.fn(),
  // RunNowSection polls this on mount; default to idle so sibling sections'
  // tests don't have to know about it.
  getAgentStatus: vi
    .fn()
    .mockResolvedValue({ running: false, lastStartedAt: null, lastFinishedAt: null, lastExitCode: null }),
  triggerAgentRun: vi.fn(),
  getProfileAnswers: vi.fn(),
  getRouting: vi.fn(),
  listConnections: vi.fn(),
  listConnectionModels: vi.fn(),
  listRuns: vi.fn().mockResolvedValue([]),
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
    jobBoards: [],
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

function makeProfile(overrides: Partial<JobProfile> = {}): JobProfile {
  return {
    name: "",
    enabled: true,
    keywords: [],
    locations: [],
    remoteModel: null,
    employmentCountry: null,
    eorAllowed: null,
    requireEntityVerification: true,
    salaryFloor: null,
    salaryAskMin: null,
    salaryAskMax: null,
    currency: "EUR",
    workingLanguage: null,
    glassdoorMin: null,
    glassdoorMinReviews: null,
    acceptedRoleTypes: [],
    rejectedRoleTypes: [],
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

function makeRouting(overrides: Partial<Routing> = {}): Routing {
  return {
    tasks: {},
    agent: null,
    default: null,
    ...overrides,
  };
}

async function renderLoaded(config: AgentConfig) {
  const connections: ConnectionList = { encryptionAvailable: true, connections: [] };
  vi.mocked(getAgentConfig).mockResolvedValue(config);
  vi.mocked(getProfileAnswers).mockResolvedValue(makeAnswers());
  vi.mocked(getRouting).mockResolvedValue(makeRouting());
  vi.mocked(listConnections).mockResolvedValue(connections);
  vi.mocked(listConnectionModels).mockResolvedValue([]);
  render(
    <MemoryRouter>
      <AgentsPage onBack={vi.fn()} />
    </MemoryRouter>,
  );
  await screen.findByRole("heading", { name: "Job profiles" });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AgentsPage profiles section", () => {
  it("round-trips a comma-delimited field: typed 'a, b' saves as ['a','b'] and renders back as 'a, b'", async () => {
    await renderLoaded(makeConfig());

    fireEvent.click(screen.getByRole("button", { name: "Add profile" }));
    const keywords = screen.getByLabelText("Keywords");
    fireEvent.change(keywords, { target: { value: "a, b" } });

    vi.mocked(updateAgentConfig).mockResolvedValueOnce(
      makeConfig({ profiles: [makeProfile({ keywords: ["a", "b"] })] }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save profiles" }));

    await vi.waitFor(() => {
      expect((screen.getByLabelText("Keywords") as HTMLInputElement).value).toBe("a, b");
    });
  });

  it("leaves a blank multi-item/numeric field as its off value ([] / null), not [\"\"] or 0", async () => {
    await renderLoaded(makeConfig());

    fireEvent.click(screen.getByRole("button", { name: "Add profile" }));
    // Clear Keywords and Salary floor which are pre-filled; they should round-trip as [] and null.
    fireEvent.change(screen.getByLabelText("Keywords"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Salary floor"), { target: { value: "" } });
    vi.mocked(updateAgentConfig).mockResolvedValueOnce(
      makeConfig({ profiles: [makeProfile()] }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save profiles" }));

    await vi.waitFor(() => expect(updateAgentConfig).toHaveBeenCalled());
    const body = vi.mocked(updateAgentConfig).mock.calls[0][0];
    expect(body.profiles?.[0]?.keywords).toEqual([]);
    expect(body.profiles?.[0]?.salaryFloor).toBeNull();
  });

  it("saving profiles sends only profile-shaped keys, never the schedule's or blocklist's fields", async () => {
    await renderLoaded(makeConfig());

    vi.mocked(updateAgentConfig).mockResolvedValueOnce(makeConfig());
    fireEvent.click(screen.getByRole("button", { name: "Save profiles" }));

    await vi.waitFor(() => expect(updateAgentConfig).toHaveBeenCalled());
    const body = vi.mocked(updateAgentConfig).mock.calls[0][0];
    // cooldownDays is deliberately absent: the cooldown windows' single
    // writer is Settings' Job search policy section.
    expect(Object.keys(body).sort()).toEqual(
      ["maxApplicationsPerRun", "maxPostingAgeDays", "profiles"].sort(),
    );
    expect(body).not.toHaveProperty("cooldownDays");
    expect(body).not.toHaveProperty("cooldownDaysSameRole");
    expect(body).not.toHaveProperty("cooldownDaysSameCompany");
    expect(body).not.toHaveProperty("runAt");
    expect(body).not.toHaveProperty("runDays");
    expect(body).not.toHaveProperty("blockedCompanies");

    // The other sections are still on the page, untouched by the profiles save.
    expect(screen.getByRole("heading", { name: "Schedule" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Blocked companies" })).toBeTruthy();
  });

  it("EOR allowed renders MUI MenuItem options (not raw <option>s); picking one updates the field and closes the menu", async () => {
    await renderLoaded(makeConfig({ profiles: [makeProfile({ name: "P1" })] }));

    fireEvent.mouseDown(screen.getByLabelText("EOR allowed"));
    const notSet = screen.getByRole("option", { name: "Not set" });
    const allowed = screen.getByRole("option", { name: "Allowed" });
    const notAllowed = screen.getByRole("option", { name: "Not allowed" });
    // Real <option> elements would fail this — MUI menus render <li role="option">.
    expect(notSet.tagName).toBe("LI");
    expect(allowed.tagName).toBe("LI");
    expect(notAllowed.tagName).toBe("LI");

    fireEvent.click(allowed);

    // The menu closes on selection.
    await vi.waitFor(() => {
      expect(screen.queryByRole("option", { name: "Allowed" })).toBeNull();
    });

    vi.mocked(updateAgentConfig).mockResolvedValueOnce(
      makeConfig({ profiles: [makeProfile({ name: "P1", eorAllowed: true })] }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save profiles" }));

    await vi.waitFor(() => expect(updateAgentConfig).toHaveBeenCalled());
    const body = vi.mocked(updateAgentConfig).mock.calls[0][0];
    expect(body.profiles?.[0]?.eorAllowed).toBe(true);
  });

  it("adding a profile and saving without editing it persists the prefilled defaults", async () => {
    await renderLoaded(makeConfig());

    fireEvent.click(screen.getByRole("button", { name: "Add profile" }));

    vi.mocked(updateAgentConfig).mockResolvedValueOnce(
      makeConfig({ profiles: [makeProfile({ name: "New profile" })] }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save profiles" }));

    await vi.waitFor(() => expect(updateAgentConfig).toHaveBeenCalled());
    const body = vi.mocked(updateAgentConfig).mock.calls[0][0];
    expect(body.profiles).toEqual([
      {
        name: "New profile",
        enabled: true,
        keywords: [],
        locations: [],
        remoteModel: "remote",
        employmentCountry: "Germany",
        eorAllowed: false,
        requireEntityVerification: true,
        salaryFloor: 70000,
        salaryAskMin: 80000,
        salaryAskMax: 100000,
        // No regional default: a new profile starts with no currency set.
        currency: null,
        workingLanguage: null,
        glassdoorMin: null,
        glassdoorMinReviews: null,
        acceptedRoleTypes: [],
        rejectedRoleTypes: [],
      },
    ]);
  });

  it("a profile's currency survives an edit and save unchanged", async () => {
    // The UI has no currency control, and PUT replaces profiles wholesale, so
    // dropping the field here would silently reset a hand-set currency to EUR
    // and make recommend_salary quote the wrong unit.
    await renderLoaded(makeConfig({ profiles: [makeProfile({ name: "UK", currency: "GBP" })] }));

    fireEvent.change(screen.getByLabelText("Salary ask min"), { target: { value: "80000" } });
    vi.mocked(updateAgentConfig).mockResolvedValueOnce(
      makeConfig({ profiles: [makeProfile({ name: "UK", currency: "GBP" })] }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save profiles" }));

    await vi.waitFor(() => expect(updateAgentConfig).toHaveBeenCalled());
    const body = vi.mocked(updateAgentConfig).mock.calls[0][0];
    expect(body.profiles?.[0].currency).toBe("GBP");
  });

  it("clearing a profile's name to blank and saving shows an inline error and makes no API call", async () => {
    await renderLoaded(makeConfig());

    fireEvent.click(screen.getByRole("button", { name: "Add profile" }));
    // Target the first Name field (the profile name, not the answer), which comes before Keywords
    const nameFields = screen.getAllByLabelText("Name");
    fireEvent.change(nameFields[0], { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save profiles" }));

    expect(await screen.findByText("Profile name is required")).toBeTruthy();
    expect(updateAgentConfig).not.toHaveBeenCalled();
  });

  it("the profile answers section neither renders nor saves a salary expectation", async () => {
    // Salary now comes from the matched job profile's clamped ask band. If a
    // free-text salary answer survived here it would race that band and the
    // agent could type a figure the guardrail never approved.
    await renderLoaded(makeConfig());

    expect(screen.queryByLabelText("Salary expectation")).toBeNull();

    vi.mocked(saveProfileAnswers).mockResolvedValueOnce(makeAnswers());
    fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "555-0100" } });
    fireEvent.click(screen.getByRole("button", { name: "Save answers" }));

    await vi.waitFor(() => expect(saveProfileAnswers).toHaveBeenCalled());
    expect(Object.keys(vi.mocked(saveProfileAnswers).mock.calls[0][0]).sort()).toEqual([
      "authorizedNonGermanCountry",
      "csDegree",
      "currentRole",
      "email",
      "gender",
      "github",
      "gpa",
      "highestRelevantDegree",
      "howDidYouHear",
      "languages",
      "linkedin",
      "locationPreference",
      "name",
      "noticePeriod",
      "otherDegree",
      "phone",
      "requiresSponsorship",
      "website",
      "workAuthorisation",
      "yearsOfExperience",
    ]);
  });

  it("editing a new field like current role and saving includes it in the PUT body", async () => {
    await renderLoaded(makeConfig());

    vi.mocked(saveProfileAnswers).mockResolvedValueOnce(makeAnswers());
    fireEvent.change(screen.getByLabelText("Current role"), {
      target: { value: "Staff Engineer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save answers" }));

    await vi.waitFor(() => expect(saveProfileAnswers).toHaveBeenCalled());
    const body = vi.mocked(saveProfileAnswers).mock.calls[0][0];
    expect(body.currentRole).toBe("Staff Engineer");
  });

  it("a salary floor above the ask minimum shows an inline error and makes no API call", async () => {
    await renderLoaded(makeConfig());

    fireEvent.click(screen.getByRole("button", { name: "Add profile" }));
    fireEvent.change(screen.getByLabelText("Salary floor"), { target: { value: "100000" } });
    fireEvent.change(screen.getByLabelText("Salary ask min"), { target: { value: "90000" } });
    fireEvent.click(screen.getByRole("button", { name: "Save profiles" }));

    expect(await screen.findByText("Salary floor must be <= ask minimum")).toBeTruthy();
    expect(updateAgentConfig).not.toHaveBeenCalled();
  });

  it("no longer offers a per-profile Preferred sources field", async () => {
    await renderLoaded(makeConfig());

    fireEvent.click(screen.getByRole("button", { name: "Add profile" }));
    expect(screen.queryByLabelText("Preferred sources")).toBeNull();
  });
});
