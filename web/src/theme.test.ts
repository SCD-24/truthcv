import { describe, expect, it } from "vitest";
import { theme } from "./theme";

describe("theme", () => {
  // Palette text colours must be CSS vars so tokens.css can flip them in
  // dark mode; concrete hexes here are the dark-text-on-dark-ground bug.
  it("uses token vars for text colours", () => {
    expect(theme.palette.text.primary).toBe("var(--ink)");
    expect(theme.palette.text.secondary).toBe("var(--ink-soft)");
  });
});
