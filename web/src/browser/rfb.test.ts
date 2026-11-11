import { describe, expect, it, vi } from "vitest";

import { unwrapRfbConstructor } from "./rfb";

// The real noVNC module uses top-level await and touches `window` at load, so
// it must never be imported here. The helper under test only needs its shape.
vi.mock("@novnc/novnc/lib/rfb", () => ({ default: class {} }));

class FakeRfb {}

describe("unwrapRfbConstructor", () => {
  it("returns the class when it is passed directly", () => {
    expect(unwrapRfbConstructor(FakeRfb)).toBe(FakeRfb);
  });

  it("unwraps a { default: Class } module", () => {
    expect(unwrapRfbConstructor({ default: FakeRfb })).toBe(FakeRfb);
  });

  it("unwraps a { default: { __esModule, default: Class } } module", () => {
    expect(unwrapRfbConstructor({ default: { __esModule: true, default: FakeRfb } })).toBe(FakeRfb);
  });

  it("throws when no constructor is present", () => {
    expect(() => unwrapRfbConstructor({ default: { default: "not a class" } })).toThrow(
      /noVNC RFB constructor not found/
    );
  });
});
