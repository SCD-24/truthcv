import { describe, expect, it } from "vitest";
import { STEPS } from "./wizard/steps";
import { stepIdFromPath, stepPath } from "./routes";

describe("stepPath / stepIdFromPath", () => {
  it("round-trips every known step id", () => {
    for (const step of STEPS) {
      expect(stepIdFromPath(stepPath(step.id))).toBe(step.id);
    }
  });

  it("returns null for non-step paths", () => {
    expect(stepIdFromPath("/cv")).toBeNull();
    expect(stepIdFromPath("/analytics")).toBeNull();
    expect(stepIdFromPath("/cv/bogus")).toBeNull();
  });
});
