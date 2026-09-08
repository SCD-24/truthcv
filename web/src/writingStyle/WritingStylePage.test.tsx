// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import {
  deletePromptFragment,
  listPromptFragments,
  listPromptPresets,
  savePromptFragment,
  savePromptPreset,
  setDefaultPromptPreset,
} from "../api/client";
import type { PromptFragment, PromptPreset } from "../api/client";
import { WritingStylePage } from "./WritingStylePage";

vi.mock("../api/client", () => ({
  listPromptFragments: vi.fn(),
  savePromptFragment: vi.fn(),
  deletePromptFragment: vi.fn(),
  listPromptPresets: vi.fn(),
  savePromptPreset: vi.fn(),
  deletePromptPreset: vi.fn(),
  setDefaultPromptPreset: vi.fn(),
}));

const FRAGMENTS: PromptFragment[] = [
  { id: "voice-1", slot: "voice", title: "Warm voice", text: "Be warm.", seeded: true, recommended: false },
  { id: "voice-2", slot: "voice", title: "Direct voice", text: "Be direct.", seeded: true, recommended: false },
  { id: "structure-1", slot: "structure", title: "Three paragraphs", text: "Use 3 paragraphs.", seeded: true, recommended: false },
  { id: "rules-1", slot: "rules", title: "Letter style", text: "Keep to one page.", seeded: true, recommended: true },
  { id: "voice-user", slot: "voice", title: "My voice", text: "Mine.", seeded: false, recommended: false },
];

const PRESETS: PromptPreset[] = [
  { id: "professional", name: "Professional", fragmentIds: ["voice-2", "structure-1"], isDefault: true, seeded: true },
  { id: "warm", name: "Warm", fragmentIds: ["voice-1", "structure-1"], isDefault: false, seeded: true },
  { id: "concise", name: "Concise", fragmentIds: ["voice-2"], isDefault: false, seeded: true },
];

beforeEach(() => {
  vi.mocked(listPromptFragments).mockResolvedValue(FRAGMENTS);
  vi.mocked(listPromptPresets).mockResolvedValue(PRESETS);
  vi.mocked(savePromptPreset).mockResolvedValue(PRESETS[0]);
  vi.mocked(setDefaultPromptPreset).mockResolvedValue(PRESETS[0]);
  vi.mocked(savePromptFragment).mockResolvedValue(FRAGMENTS[4]);
  vi.mocked(deletePromptFragment).mockResolvedValue(undefined);
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

/** Picks a preset in the builder's MUI select, which renders a listbox on
 * mousedown rather than a native <select> a change event could target. */
async function selectPreset(name: string) {
  const presetBuilder = within(screen.getByRole("region", { name: "Preset builder" }));
  fireEvent.mouseDown(presetBuilder.getByRole("combobox"));
  const listbox = within(await screen.findByRole("listbox"));
  fireEvent.click(listbox.getByRole("option", { name }));
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

  it("renders the cover-letter-writing-style heading", async () => {
    render(<WritingStylePage />);
    await (await findLibrary()).findByText("Warm voice");

    expect(screen.getByRole("heading", { name: "Cover letter writing style", level: 1 })).toBeTruthy();
  });

  it("warns that fragments are combined as written with nothing checking them against one another", async () => {
    render(<WritingStylePage />);
    await (await findLibrary()).findByText("Warm voice");

    expect(
      screen.getByText(/fragments are combined exactly as written and nothing checks them/i),
    ).toBeTruthy();
  });

  it("leaves Save enabled when both voice fragments are selected", async () => {
    render(<WritingStylePage />);
    await (await findLibrary()).findByText("Warm voice");

    const presetBuilder = within(screen.getByRole("region", { name: "Preset builder" }));
    fireEvent.change(presetBuilder.getByLabelText("Preset name"), {
      target: { value: "Both voices" },
    });
    fireEvent.click(presetBuilder.getByRole("checkbox", { name: "Warm voice" }));
    fireEvent.click(presetBuilder.getByRole("checkbox", { name: "Direct voice" }));

    const saveButton = screen.getByRole("button", { name: "Save preset" }) as HTMLButtonElement;
    expect(saveButton.disabled).toBe(false);

    fireEvent.click(saveButton);

    await waitFor(() =>
      expect(savePromptPreset).toHaveBeenCalledWith({
        id: "",
        name: "Both voices",
        fragmentIds: ["voice-1", "voice-2"],
        isDefault: false,
      }),
    );
  });

  it("calls savePromptPreset with the selected fragments when Save is clicked", async () => {
    render(<WritingStylePage />);
    await (await findLibrary()).findByText("Warm voice");

    const presetBuilder = within(screen.getByRole("region", { name: "Preset builder" }));
    fireEvent.change(presetBuilder.getByLabelText("Preset name"), {
      target: { value: "My preset" },
    });
    fireEvent.click(presetBuilder.getByRole("checkbox", { name: "Warm voice" }));

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

  it("disables Save when a seeded preset is selected", async () => {
    render(<WritingStylePage />);
    await (await findLibrary()).findByText("Warm voice");

    await selectPreset("Professional (default)");

    const saveButton = screen.getByRole("button", { name: "Save preset" }) as HTMLButtonElement;
    await waitFor(() => expect(saveButton.disabled).toBe(true));
    expect(screen.getByText(/shipped presets can't be edited/i)).toBeTruthy();
  });

  it("expands fragment text when the expand button is clicked", async () => {
    render(<WritingStylePage />);
    const library = await findLibrary();
    await library.findByText("Warm voice");

    // Initially the text is hidden
    expect(library.queryByText("Be warm.")).toBeNull();

    // Click the expand button for "Warm voice"
    const expandButton = library.getByRole("button", { name: "Show text for Warm voice" });
    fireEvent.click(expandButton);

    // Text becomes visible
    expect(library.getByText("Be warm.")).toBeTruthy();
  });

  it("warns when a preset omits recommended fragments", async () => {
    render(<WritingStylePage />);
    const library = await findLibrary();
    await library.findByText("Warm voice");

    const presetBuilder = within(screen.getByRole("region", { name: "Preset builder" }));

    fireEvent.change(presetBuilder.getByLabelText("Preset name"), {
      target: { value: "Test preset" },
    });

    // Select only "Warm voice" (rules-1 is recommended but not selected)
    fireEvent.click(presetBuilder.getByRole("checkbox", { name: "Warm voice" }));

    // Check that the recommended warning appears
    await waitFor(() => {
      const statusBox = screen.getByRole("status");
      expect(statusBox.textContent).toMatch(/recommended fragments not selected/i);
      expect(statusBox.textContent).toMatch(/letter style/i);
    });

    // The Save button should still be enabled
    const saveButton = screen.getByRole("button", { name: "Save preset" }) as HTMLButtonElement;
    expect(saveButton.disabled).toBe(false);

    // Select the recommended fragment
    fireEvent.click(presetBuilder.getByRole("checkbox", { name: "Letter style" }));

    // The warning should disappear
    await waitFor(() => {
      const statusBox = screen.getByRole("status");
      expect(statusBox.textContent).not.toMatch(/recommended fragments not selected/i);
    });
  });

  it("shows the server error when saving a fragment fails", async () => {
    vi.mocked(savePromptFragment).mockRejectedValue(new Error("Title is required."));
    render(<WritingStylePage />);
    const library = await findLibrary();
    await library.findByText("My voice");

    fireEvent.click(library.getByRole("button", { name: "Edit My voice" }));
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));

    // Queried by text, not role: the open dialog aria-hides the page behind it,
    // and MUI's informational alerts also carry role="alert".
    expect(await screen.findByText(/title is required/i)).toBeTruthy();
  });

  it("shows the server error when deleting a fragment fails", async () => {
    vi.mocked(deletePromptFragment).mockRejectedValue(new Error("Fragment is in use."));
    render(<WritingStylePage />);
    const library = await findLibrary();
    await library.findByText("My voice");

    fireEvent.click(library.getByRole("button", { name: "Delete My voice" }));

    expect(await screen.findByText(/fragment is in use/i)).toBeTruthy();
  });

  it("shows the server error when saving a preset fails", async () => {
    vi.mocked(savePromptPreset).mockRejectedValue(new Error("Name already taken."));
    render(<WritingStylePage />);
    await (await findLibrary()).findByText("Warm voice");

    const presetBuilder = within(screen.getByRole("region", { name: "Preset builder" }));
    fireEvent.change(presetBuilder.getByLabelText("Preset name"), {
      target: { value: "My preset" },
    });
    fireEvent.click(presetBuilder.getByRole("checkbox", { name: "Warm voice" }));

    const saveButton = screen.getByRole("button", { name: "Save preset" }) as HTMLButtonElement;
    await waitFor(() => expect(saveButton.disabled).toBe(false));
    fireEvent.click(saveButton);

    expect(await screen.findByText(/name already taken/i)).toBeTruthy();
  });

  it("shows the server error when setting the default preset fails", async () => {
    vi.mocked(setDefaultPromptPreset).mockRejectedValue(new Error("Only saved presets can be default."));
    render(<WritingStylePage />);
    await (await findLibrary()).findByText("Warm voice");

    await selectPreset("Warm");
    fireEvent.click(screen.getByRole("button", { name: "Set as default" }));

    expect(await screen.findByText(/only saved presets can be default/i)).toBeTruthy();
  });
});
