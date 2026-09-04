// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { getTruth, saveTruth } from "../api/client";
import type { TruthDoc } from "../api/types";
import { WizardProvider } from "../wizard/store";
import { TruthFilePage } from "./TruthFilePage";

vi.mock("../api/client", () => ({
  getTruth: vi.fn(),
  saveTruth: vi.fn(),
  getOnboarding: vi.fn().mockResolvedValue({
    providerDone: true,
    hasProfile: true,
    cvReviewedAt: "2024-01-01T00:00:00.000Z",
    tourSeenAt: "2024-01-01T00:00:00.000Z",
    complete: true,
  }),
  getProfile: vi.fn().mockResolvedValue({ hasProfile: true }),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function emptyTruth(): TruthDoc {
  return {
    experiences: [],
    education: [],
    skills: [],
    hobbies: [],
    profile: { name: "", email: "", phone: "", location: "", links: [], summary: "" },
  };
}

function seedTruth(): TruthDoc {
  return {
    experiences: [
      {
        id: "exp-cv-1",
        role: "Engineer",
        company: "Acme Corp",
        start: "2020-01",
        end: "2022-06",
        source: "linkedin-pdf",
        bullets: [
          {
            id: "bullet-cv-1",
            value: "Built systems",
            source: "linkedin-pdf",
          },
        ],
      },
    ],
    education: [],
    skills: [
      {
        id: "skill-cv-1",
        value: "React",
        source: "linkedin-pdf",
      },
      {
        id: "skill-cv-2",
        value: "TypeScript",
        source: "linkedin-pdf",
      },
    ],
    hobbies: [
      {
        id: "hobby-cv-1",
        value: "Chess",
        source: "user-confirmed",
      },
    ],
    profile: { name: "", email: "", phone: "", location: "", links: [], summary: "" },
  };
}

function renderPage(onBack = vi.fn()) {
  return render(
    <WizardProvider>
      <TruthFilePage onBack={onBack} />
    </WizardProvider>,
  );
}

describe("TruthFilePage", () => {
  it("loads the truth via getTruth and shows the title and existing skill value", async () => {
    vi.mocked(getTruth).mockResolvedValue(seedTruth());
    renderPage();

    expect(await screen.findByText("Your truth file")).toBeTruthy();
    expect(await screen.findByDisplayValue("React")).toBeTruthy();
  });

  it("editing a skill and clicking Save calls saveTruth with the edited value and shows success alert", async () => {
    vi.mocked(getTruth).mockResolvedValue(seedTruth());
    vi.mocked(saveTruth).mockResolvedValue(undefined);

    renderPage();
    await screen.findByText("Your truth file");

    // Find and edit the React skill
    const reactInput = screen.getByDisplayValue("React");
    fireEvent.change(reactInput, { target: { value: "React & Node.js" } });

    // Click Save
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    // Wait for saveTruth to be called and success alert to appear
    await waitFor(() =>
      expect(saveTruth).toHaveBeenCalledWith(
        expect.objectContaining({
          skills: expect.arrayContaining([
            expect.objectContaining({
              value: "React & Node.js",
            }),
          ]),
        }),
      ),
    );
    expect(await screen.findByText("Truth file saved.")).toBeTruthy();
  });

  it("adding a skill and clicking Save calls saveTruth with user-confirmed source", async () => {
    vi.mocked(getTruth).mockResolvedValue(emptyTruth());
    vi.mocked(saveTruth).mockResolvedValue(undefined);

    renderPage();
    await screen.findByText("Your truth file");

    // Click "+ Add skill"
    fireEvent.click(screen.getByRole("button", { name: /\+ Add skill/i }));

    // Type in the new skill input (the last one added)
    const skillInputs = screen.getAllByLabelText("Skill");
    fireEvent.change(skillInputs[skillInputs.length - 1], { target: { value: "Python" } });

    // Click Save
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    // Verify saveTruth was called with the new skill having source: "user-confirmed"
    await waitFor(() =>
      expect(saveTruth).toHaveBeenCalledWith(
        expect.objectContaining({
          skills: expect.arrayContaining([
            expect.objectContaining({
              value: "Python",
              source: "user-confirmed",
            }),
          ]),
        }),
      ),
    );
    expect(await screen.findByText("Truth file saved.")).toBeTruthy();
  });

  it("removing CV-sourced entries (skill and experience) and clicking Save removes them from saveTruth call", async () => {
    vi.mocked(getTruth).mockResolvedValue(seedTruth());
    vi.mocked(saveTruth).mockResolvedValue(undefined);

    renderPage();
    await screen.findByText("Your truth file");

    // Remove the React skill (first skill remove button)
    const removeSkillButtons = screen.getAllByRole("button", { name: /×/i });
    fireEvent.click(removeSkillButtons[0]);

    // Remove the experience by clicking "Remove job" button
    fireEvent.click(screen.getByRole("button", { name: /Remove job/i }));

    // Click Save
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    // Verify saveTruth was called with these entries removed
    await waitFor(() => {
      const call = vi.mocked(saveTruth).mock.calls[0]?.[0];
      expect(call?.experiences).toEqual([]);
      expect(call?.skills.length).toBe(1);
      expect(call?.skills[0]?.value).toBe("TypeScript");
    });
    expect(await screen.findByText("Truth file saved.")).toBeTruthy();
  });

  it("clicking the Back button calls onBack", async () => {
    vi.mocked(getTruth).mockResolvedValue(emptyTruth());
    const onBack = vi.fn();
    renderPage(onBack);

    await screen.findByText("Your truth file");
    fireEvent.click(screen.getByRole("button", { name: /back/i }));

    expect(onBack).toHaveBeenCalled();
  });

  it("adds a hobby and shows it under the Hobbies heading", async () => {
    vi.mocked(getTruth).mockResolvedValue(emptyTruth());
    vi.mocked(saveTruth).mockResolvedValue(undefined);

    renderPage();
    await screen.findByText("Your truth file");

    // Click "+ Add hobby"
    fireEvent.click(screen.getByRole("button", { name: /\+ Add hobby/i }));

    // Type in the new hobby input (the last one added)
    const hobbyInputs = screen.getAllByLabelText("Hobby");
    fireEvent.change(hobbyInputs[hobbyInputs.length - 1], { target: { value: "Chess" } });

    // Click Save
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    // Verify saveTruth was called with the new hobby having source: "user-confirmed"
    await waitFor(() =>
      expect(saveTruth).toHaveBeenCalledWith(
        expect.objectContaining({
          hobbies: expect.arrayContaining([
            expect.objectContaining({
              value: "Chess",
              source: "user-confirmed",
            }),
          ]),
        }),
      ),
    );
    expect(await screen.findByText("Truth file saved.")).toBeTruthy();
  });

  it("removes a hobby and it is absent from the saveTruth call", async () => {
    const truthWithHobby = {
      ...emptyTruth(),
      hobbies: [{ id: "h1", value: "Chess", source: "user-confirmed" as const }],
    };
    vi.mocked(getTruth).mockResolvedValue(truthWithHobby);
    vi.mocked(saveTruth).mockResolvedValue(undefined);

    renderPage();
    await screen.findByText("Your truth file");

    // Ensure the hobby is displayed
    expect(screen.getByDisplayValue("Chess")).toBeTruthy();

    // Click the × button for the hobby
    const removeHobbyButtons = screen.getAllByRole("button", { name: /×/i });
    fireEvent.click(removeHobbyButtons[0]); // Remove the hobby (should be first × button)

    // Click Save
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    // Verify saveTruth was called with an empty hobbies array
    await waitFor(() => {
      const call = vi.mocked(saveTruth).mock.calls[0]?.[0];
      expect(call?.hobbies).toEqual([]);
    });
    expect(await screen.findByText("Truth file saved.")).toBeTruthy();
  });
});
