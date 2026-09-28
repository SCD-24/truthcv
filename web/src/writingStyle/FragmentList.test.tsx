// @vitest-environment jsdom
/** Fragment deletion uses a confirmation dialog, not window.confirm. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { FragmentList } from "./FragmentList";
import { deletePromptFragment } from "../api/client";
import type { PromptFragment } from "../api/client";

vi.mock("../api/client", () => ({
  deletePromptFragment: vi.fn(),
  savePromptFragment: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function makeFragment(overrides: Partial<PromptFragment> = {}): PromptFragment {
  return {
    id: "f1",
    slot: "voice",
    title: "My fragment",
    text: "some text",
    seeded: false,
    recommended: false,
    ...overrides,
  } as PromptFragment;
}

describe("FragmentList delete confirmation", () => {
  it("cancelling the dialog does not call deletePromptFragment", async () => {
    render(
      <FragmentList fragments={[makeFragment()]} onChange={() => {}} onError={() => {}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /delete my fragment/i }));

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /cancel/i }));

    expect(deletePromptFragment).not.toHaveBeenCalled();
  });

  it("confirming the dialog calls deletePromptFragment exactly once", async () => {
    vi.mocked(deletePromptFragment).mockResolvedValue(undefined as never);
    const onChange = vi.fn();
    render(
      <FragmentList fragments={[makeFragment()]} onChange={onChange} onError={() => {}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /delete my fragment/i }));

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    await screen.findByRole("button", { name: /delete my fragment/i });
    expect(deletePromptFragment).toHaveBeenCalledTimes(1);
    expect(deletePromptFragment).toHaveBeenCalledWith("f1");
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
