import { describe, expect, it } from "vitest";
import { theme } from "./theme";

describe("theme", () => {
  // Palette values must be parseable hexes, not CSS vars: MUI's createTheme
  // calls alpha() on palette colours at module-eval time, which throws on a
  // raw var() string (MUI error #9) and blanks the whole app. Dark mode
  // instead comes from a second, real MUI colour scheme mirroring tokens.css's
  // `prefers-color-scheme: dark` override — this must fail if someone
  // collapses back to a single var()-based palette.
  it("defines separate light and dark colour schemes with parseable hexes", () => {
    const light = theme.colorSchemes.light!.palette;
    const dark = theme.colorSchemes.dark!.palette;

    expect(light.text.primary).toBe("#1a211c");
    expect(light.text.secondary).toBe("#59615a");
    expect(light.background.default).toBe("#ecede6");

    expect(dark.text.primary).toBe("#e8eae2");
    expect(dark.text.secondary).toBe("#9aa197");
    expect(dark.background.default).toBe("#151814");

    for (const scheme of [light, dark]) {
      for (const value of [
        scheme.text.primary,
        scheme.text.secondary,
        scheme.background.default,
        scheme.primary.main,
        scheme.error.main,
      ]) {
        expect(value).not.toMatch(/^var\(/);
      }
    }
  });
});
