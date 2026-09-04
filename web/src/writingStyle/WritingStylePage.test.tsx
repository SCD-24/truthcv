// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import {
  listPromptFragments,
  listPromptPresets,
  savePromptPreset,
  setDefaultPromptPreset,
  validatePromptPreset,
} from "../api/client";
import type { PromptConflict, PromptFragment, PromptPreset } from "../api/client";
import { WritingStylePage } from "./WritingStylePage";

vi.mock("../api/client", () => ({
  listPromptFragments: vi.fn(),
  savePromptFragment: vi.fn(),
  deletePromptFragment: vi.fn(),
  listPromptPresets: vi.fn(),
  savePromptPreset: vi.fn(),
  deletePromptPreset: vi.fn(),
  validatePromptPreset: vi.fn(),
  setDefaultPromptPreset: vi.fn(),
}));

const FRAGMENTS: PromptFragment[] = [
  { id: "voice-1", slot: "voice", title: "Warm voice", text: "Be warm.", seeded: true, conflictsWith: [] },
  { id: "voice-2", slot: "voice", title: "Direct voice", text: "Be direct.", seeded: true, conflictsWith: [] },
  { id: "structure-1", slot: "structure", title: "Three paragraphs", text: "Use 3 paragraphs.", seeded: true, conflictsWith: [] },
];

const PRESETS: PromptPreset[] = [
  { id: "professional", name: "Professional", fragmentIds: ["voice-2", "structure-1"], isDefault: true, seeded: true },
  { id: "warm", name: "Warm", fragmentIds: ["voice-1", "structure-1"], isDefault: false, seeded: true },
  { id: "concise", name: "Concise", fragmentIds: ["voice-2"], isDefault: false, seeded: true },
];

const EXCLUSIVE_CONFLICT: PromptConflict[] = [
  {
    kind: "exclusive_slot",
    fragmentIds: ["voice-1", "voice-2"],
    slot: "voice",
    message: "Only one voice fragment may be selected at a time.",
  },
];

beforeEach(() => {
  vi.mocked(listPromptFragments).mockResolvedValue(FRAGMENTS);
  vi.mocked(listPromptPresets).mockResolvedValue(PRESETS);
  vi.mocked(validatePromptPreset).mockResolvedValue([]);
  vi.mocked(savePromptPreset).mockResolvedValue(PRESETS[0]);
  vi.mocked(setDefaultPromptPreset).mockResolvedValue(PRESETS[0]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

/** Queries scoped to the fragment library panel. Fragment titles also appear
 * as checkbox labels in the preset builder, so page-wide text queries are
 * ambiguous by design. */
async function findLibrary() {
  return within(await screen.findByRole("region", { name: "Prompt fragments" }));
}

describe("WritingStylePage", () => {
  it("renders seeded fragments grouped by slot", async () => {
    render(<WritingStylePage />);

    const library = await findLibrary();
    expect(await library.findByText("Warm voice")).toBeTruthy();
    expect(library.getByText("Direct voice")).toBeTruthy();
    expect(library.getByText("Three paragraphs")).toBeTruthy();
    // Slot group headings.
    expect(screen.getByRole("heading", { name: "voice" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "structure" })).toBeTruthy();
  });

  it("shows a conflict and disables Save when two voice fragments are both selected", async () => {
    render(<WritingStylePage />);
    await (await findLibrary()).findByText("Warm voice");

    fireEvent.click(screen.getByRole("checkbox", { name: "Warm voice" }));
    vi.mocked(validatePromptPreset).mockResolvedValue(EXCLUSIVE_CONFLICT);
    fireEvent.click(screen.getByRole("checkbox", { name: "Direct voice" }));

    // The message shows in the conflict alert and inline beside each
    // offending checkbox; assert on the alert.
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/only one voice fragment/i)).toBeTruthy();
    const saveButton = screen.getByRole("button", { name: "Save preset" }) as HTMLButtonElement;
    await waitFor(() => expect(saveButton.disabled).toBe(true));
  });

  it("calls savePromptPreset with the selected fragments when Save is clicked", async () => {
    render(<WritingStylePage />);
    await (await findLibrary()).findByText("Warm voice");

    fireEvent.change(screen.getByLabelText("Preset name"), {
      target: { value: "My preset" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Warm voice" }));

    await waitFor(() => expect(validatePromptPreset).toHaveBeenCalledWith(["voice-1"]));

    const saveButton = screen.getByRole("button", { name: "Save preset" }) as HTMLButtonElement;
    await waitFor(() => expect(saveButton.disabled).toBe(false));
    fireEvent.click(saveButton);

    await waitFor(() =>
      expect(savePromptPreset).toHaveBeenCalledWith({
        id: "",
        name: "My preset",
        fragmentIds: ["voice-1"],
        isDefault: false,
      }),
    );
  });
});
