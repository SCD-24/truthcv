// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ModelInfo } from "../api/types";
import { ModelSelect } from "./ModelSelect";

/** Follows ModelRoutePicker.test.tsx's conventions: render with
 * @testing-library/react + jsdom, scoped to this file via the environment
 * docblock above. */

/** 30 generated models plus one whose id carries a distinctive substring
 * that isn't present in its label, so the id-vs-label search assertion is
 * meaningful. */
const models: ModelInfo[] = [
  ...Array.from({ length: 30 }, (_, i) => ({
    id: `provider-model-${i}`,
    label: `Model ${i}`,
  })),
  { id: "zzz-secret-id-42", label: "Special Model" },
];

function getCombobox(): HTMLElement {
  const el = screen
    .getAllByLabelText(/^model$/i)
    .find((e) => e.getAttribute("role") === "combobox");
  if (!el) throw new Error("model combobox not found");
  return el;
}

function renderModelSelect(overrides: Partial<Parameters<typeof ModelSelect>[0]> = {}) {
  const onChange = vi.fn();
  const onReload = vi.fn();
  const view = render(
    <ModelSelect
      models={models}
      model=""
      customModel={false}
      onChange={onChange}
      onReload={onReload}
      modelsLoading={false}
      modelsError={null}
      connection="claude"
      {...overrides}
    />,
  );
  return { onChange, onReload, view };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ModelSelect", () => {
  it("typing a query narrows the listbox to matching models", () => {
    renderModelSelect();
    const input = getCombobox();
    fireEvent.focus(input);
    fireEvent.mouseDown(input);
    fireEvent.change(input, { target: { value: "Model 7" } });

    expect(screen.getByRole("option", { name: "Model 7" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Model 3" })).toBeNull();
  });

  it("matches against the model id as well as the display label", () => {
    renderModelSelect();
    const input = getCombobox();
    fireEvent.focus(input);
    fireEvent.mouseDown(input);
    fireEvent.change(input, { target: { value: "secret-id" } });

    // "secret-id" only appears in the id, not the "Special Model" label.
    expect(screen.getByRole("option", { name: "Special Model" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Model 0" })).toBeNull();
  });

  it('"Provider default" and "Custom…" stay available even when the query matches no model', () => {
    renderModelSelect();
    const input = getCombobox();
    fireEvent.focus(input);
    fireEvent.mouseDown(input);
    fireEvent.change(input, { target: { value: "no-such-model-xyz" } });

    expect(screen.getByRole("option", { name: "Provider default" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Custom…" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /^Model \d+$/ })).toBeNull();
  });

  it("picking a model calls onChange with { model, customModel: false }", () => {
    const { onChange } = renderModelSelect();
    const input = getCombobox();
    fireEvent.focus(input);
    fireEvent.mouseDown(input);
    fireEvent.click(screen.getByRole("option", { name: "Model 12" }));

    expect(onChange).toHaveBeenCalledWith({ model: "provider-model-12", customModel: false });
  });

  it("picking Custom… calls onChange with { model: '', customModel: true }", () => {
    const { onChange } = renderModelSelect();
    const input = getCombobox();
    fireEvent.focus(input);
    fireEvent.mouseDown(input);
    fireEvent.click(screen.getByRole("option", { name: "Custom…" }));

    expect(onChange).toHaveBeenCalledWith({ model: "", customModel: true });
  });

  it("renders a Reload button that calls onReload, alongside the popup indicator", () => {
    const { onReload } = renderModelSelect();

    const reloadButton = screen.getByRole("button", { name: /^reload$/i });
    fireEvent.click(reloadButton);
    expect(onReload).toHaveBeenCalled();

    // Guards the endAdornment merge: the Autocomplete's own popup (dropdown
    // arrow) button must still be present alongside the Reload button.
    expect(screen.getByTitle(/^open$/i)).toBeTruthy();
  });

  it("keeps the typed query when the parent re-renders (e.g. Reload flips modelsLoading)", () => {
    const { view } = renderModelSelect();
    const input = getCombobox() as HTMLInputElement;
    fireEvent.focus(input);
    fireEvent.mouseDown(input);
    fireEvent.change(input, { target: { value: "Model 7" } });

    // A parent re-render must not reset the search text back to the
    // selected option's label, which would wipe the filtered list.
    view.rerender(
      <ModelSelect
        models={models}
        model=""
        customModel={false}
        onChange={vi.fn()}
        onReload={vi.fn()}
        modelsLoading
        modelsError={null}
        connection="claude"
      />,
    );

    expect(input.value).toBe("Model 7");
    expect(screen.getByRole("option", { name: "Model 7" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Model 3" })).toBeNull();
  });

  it("in custom mode, typing in the free-text field reports customModel: true", () => {
    const { onChange } = renderModelSelect({ customModel: true });

    const custom = screen.getByPlaceholderText("Exact model id");
    fireEvent.change(custom, { target: { value: "my-finetune-x" } });

    expect(onChange).toHaveBeenCalledWith({ model: "my-finetune-x", customModel: true });
  });

  it("with modelsError set, the helper text still tells the user they can pick Custom or reload", () => {
    renderModelSelect({ modelsError: "Couldn't reach the connection." });

    expect(
      screen.getByText("Couldn't reach the connection. You can still pick Custom or reload."),
    ).toBeTruthy();
  });
});
