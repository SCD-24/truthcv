import { describe, it, expect } from "vitest";
import { errorDetailToMessage } from "./errorDetail";

describe("errorDetailToMessage — string detail", () => {
  it("passes a string detail through unchanged", () => {
    expect(errorDetailToMessage({ detail: "Company already blocked" })).toBe(
      "Company already blocked",
    );
  });
});

describe("errorDetailToMessage — array detail", () => {
  it("formats a single validation error as 'field: msg'", () => {
    const body = {
      detail: [
        { loc: ["body", "profiles"], msg: "profile name must not be empty", type: "value_error" },
      ],
    };
    expect(errorDetailToMessage(body)).toBe("profiles: profile name must not be empty");
  });

  it("formats multiple validation errors, joined with '; '", () => {
    const body = {
      detail: [
        { loc: ["body", "profiles"], msg: "profile name must not be empty", type: "value_error" },
        { loc: ["body", "salaryFloor"], msg: "must be > 0", type: "value_error" },
      ],
    };
    expect(errorDetailToMessage(body)).toBe(
      "profiles: profile name must not be empty; salaryFloor: must be > 0",
    );
  });

  it("returns an empty string for an empty array detail", () => {
    expect(errorDetailToMessage({ detail: [] })).toBe("");
  });
});

describe("errorDetailToMessage — object detail (guardrail block)", () => {
  it("renders the message plus each blocked claim's text", () => {
    const body = {
      detail: {
        message: "The letter was blocked by the truthfulness guardrail.",
        blockedReason: "unverifiable",
        blockedClaims: [
          { scope_id: "para-1", text: "Led a team of 50 engineers.", tokens: ["50"] },
        ],
      },
    };
    expect(errorDetailToMessage(body)).toBe(
      "The letter was blocked by the truthfulness guardrail. Blocked: Led a team of 50 engineers.",
    );
  });

  it("joins multiple blocked claims with '; '", () => {
    const body = {
      detail: {
        message: "Blocked.",
        blockedClaims: [{ text: "Claim one." }, { text: "Claim two." }],
      },
    };
    expect(errorDetailToMessage(body)).toBe("Blocked. Blocked: Claim one.; Claim two.");
  });

  it("renders just the message when there are no blocked claims", () => {
    expect(errorDetailToMessage({ detail: { message: "Something went wrong." } })).toBe(
      "Something went wrong.",
    );
  });

  it("returns an empty string when the object has neither message nor blocked claims", () => {
    expect(errorDetailToMessage({ detail: { blockedReason: "unverifiable" } })).toBe("");
  });
});

describe("errorDetailToMessage — unparseable bodies", () => {
  it("returns an empty string for null", () => {
    expect(errorDetailToMessage(null)).toBe("");
  });

  it("returns an empty string for undefined", () => {
    expect(errorDetailToMessage(undefined)).toBe("");
  });

  it("returns an empty string for a garbage body", () => {
    expect(errorDetailToMessage("not an object")).toBe("");
    expect(errorDetailToMessage(42)).toBe("");
    expect(errorDetailToMessage({})).toBe("");
  });
});
